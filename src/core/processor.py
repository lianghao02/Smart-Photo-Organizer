# -*- coding: utf-8 -*-
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Dict, Any
import threading
import os
import shutil
import csv
import time

from src.utils.config import ConfigConstants
from src.utils.logger import Logger
from src.utils.fs_utils import FSUtils
from src.core.date_parser import DateParser
from src.core.dedup import Dedup
from src.core.image_ops import ImageOps

class Processor:
    def __init__(self, config_options: dict, 
                 progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 status_callback: Optional[Callable[[str], None]] = None):
        """
        config_options: {
            'mode': 'copy' | 'move',
            'clean_empty': bool,
            'rename_enabled': bool,
            'gps_enabled': bool,
            'resume_enabled': bool,
            'blur_check_enabled': bool,
            'skip_existing': bool,
            'dry_run': bool,
            'src_root': str,
            'dst_root': str
        }
        """
        self.config = config_options
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()
        
        self.logger = Logger.get_instance()
        self.date_parser = DateParser()
        
        self.stats = {
            "processed": 0, "processed_size": 0, "total_size": 0,
            "skipped": 0, "errors": 0, "failed_files": []
        }
        
        # Caches
        self.seen_files = {} # {size: {hash: original_path}} (Source local)
        self.dst_index = {} # {size: {hash: existing_path}} (Destination global)
        self.dir_counters = {} # {(dir, prefix): seq}
        self.history_db = {}
        
        # Dry Run
        self.dry_run_paths = set() # Set of virtual destination paths
        self.preview_log = [] # List of [Source, Action, Destination]
        
        # Thread Locks
        self.stats_lock = threading.Lock()
        self.history_lock = threading.Lock()
        self.naming_lock = threading.Lock()
        self.dedup_lock = threading.Lock()
        self.preview_lock = threading.Lock()
        
    def stop(self):
        self.stop_event.set()
        self.pause_event.set() # Unpause to exit loop

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()
        
    def start(self):
        try:
            self._load_history()
            
            src_root = self.config['src_root']
            dst_root = self.config['dst_root']
            mode_str = self.config['mode'].upper()
            if self.config.get('dry_run', False):
                mode_str += " (預覽模式 - 不寫入)"
            
            self.logger.info(f"=== 開始任務 ===\n來源: {src_root}\n目標: {dst_root}\n模式: {mode_str}")
            
            # 0. Index Destination (if enabled)
            if self.config.get('skip_existing', False):
                if self.status_callback: self.status_callback("正在建立目標資料夾索引 (去重用)...")
                self._index_destination(dst_root)
                self.logger.info(f"目標索引建立完成: {sum(len(v) for v in self.dst_index.values())} 個不重複檔案")

            # 1. Scan
            if self.status_callback: self.status_callback("正在掃描檔案...")
            all_files, total_size = self._scan_files(src_root)
            total_count = len(all_files)
            
            with self.stats_lock:
                self.stats['total_size'] = total_size

            if total_count == 0:
                self.logger.warn("找不到任何檔案。")
                return self.stats

            self.logger.info(f"共發現 {total_count} 個檔案 ({self._format_bytes(total_size)})。開始並行處理...")
            
            # 2. Process (Multi-threading)
            max_workers = min(32, (os.cpu_count() or 1) + 4)
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self._process_single_file, f, dst_root): f for f in all_files}
                
                completed_count = 0
                for future in concurrent.futures.as_completed(futures):
                    if self.stop_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                        
                    self.pause_event.wait()
                    completed_count += 1
                    file_path = futures[future]
                    
                    # Calculate Metrics
                    if self.progress_callback:
                        elapsed = time.time() - start_time
                        if elapsed < 0.001: elapsed = 0.001
                        
                        current_processed_size = self.stats['processed_size'] # Approximate (thread-safeish read)
                        speed = current_processed_size / elapsed # bytes/sec
                        
                        remaining_bytes = max(0, total_size - current_processed_size)
                        eta = remaining_bytes / speed if speed > 0 else 0
                        
                        progress_data = {
                            'current': completed_count,
                            'total': total_count,
                            'filename': os.path.basename(file_path),
                            'processed_size': current_processed_size,
                            'total_size': total_size,
                            'speed': speed,
                            'eta': eta
                        }
                        
                        if completed_count % 5 == 0 or completed_count == total_count:
                             self.progress_callback(progress_data)
                    
                    try:
                        future.result()
                    except Exception as e:
                        with self.stats_lock:
                            self.stats['errors'] += 1
                            err_msg = f"{file_path} (例外錯誤: {str(e)})"
                            self.stats['failed_files'].append(err_msg)
                        self.logger.error(f"處理失敗: {os.path.basename(file_path)} - {e}")

            # Notify 100%
            if self.progress_callback: 
                self.progress_callback({
                    'current': total_count, 'total': total_count, 
                    'filename': "Finished", 
                    'processed_size': total_size, 'total_size': total_size,
                    'speed': 0, 'eta': 0
                })

            if not self.config.get('dry_run', False):
                self._save_history()

            # 3. Clean Empty Folders
            if self.config['mode'] == 'move' and self.config['clean_empty'] and not self.stop_event.is_set():
                if self.config.get('dry_run', False):
                    self.logger.info("[預覽] 模擬清理空資料夾 (不實際執行)")
                else:
                    self.logger.info("正在清理空資料夾...")
                    FSUtils.remove_empty_folders(src_root)
            
            if self.config.get('dry_run', False):
                self._export_preview_report()

            return self.stats
            
        except Exception as e:
            self.logger.error(f"嚴重錯誤: {e}")
            raise e

    def _format_bytes(self, size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def _export_preview_report(self):
        try:
            report_path = os.path.join(os.getcwd(), "preview_report.csv")
            with open(report_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["Source File", "Action", "Destination File", "Note"])
                writer.writerows(self.preview_log)
            self.logger.info(f"預覽報告已產生: {report_path}")
            if self.status_callback: self.status_callback(f"預覽完成，請查看 {report_path}")
        except Exception as e:
            self.logger.error(f"無法寫入預覽報告: {e}")

    def _index_destination(self, dst_root):
        if not os.path.exists(dst_root): return
        
        count = 0
        for r, d, f in os.walk(dst_root):
            if self.stop_event.is_set(): break
            for file in f:
                fp = os.path.join(r, file)
                try:
                    sz = os.path.getsize(fp)
                    if sz not in self.dst_index:
                         self.dst_index[sz] = []
                    self.dst_index[sz].append(fp)
                    
                    count += 1
                    if count % 1000 == 0 and self.status_callback:
                        self.status_callback(f"正在索引目標檔案... ({count})")
                except: pass

    def _scan_files(self, root):
        files_list = []
        total_size = 0
        scan_count = 0
        for r, d, f in os.walk(root):
            if self.stop_event.is_set(): break
            for file in f:
                fp = os.path.join(r, file)
                files_list.append(fp)
                try: total_size += os.path.getsize(fp)
                except: pass
                
                scan_count += 1
                if scan_count % 1000 == 0 and self.status_callback:
                    self.status_callback(f"正在掃描... 已發現 {scan_count} 個檔案")
        return files_list, total_size

    def _process_single_file(self, file_path, dst_root):
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        
        try:
            f_size = os.path.getsize(file_path)
        except:
            f_size = 0
            
        # Resume Check
        if self.config['resume_enabled'] and self._is_already_processed(file_path, f_size):
            with self.stats_lock:
                self.stats['skipped'] += 1
                self.stats['processed_size'] += f_size
            return

        if ext in ConfigConstants.EXT_JUNK:
            return

        # Screenshot
        SCREENSHOT_KEYWORDS = ['screenshot', 'screen shot', 'captura', '螢幕擷取', '截圖', 'snapshot']
        if any(kw in filename.lower() for kw in SCREENSHOT_KEYWORDS):
            self._move_or_copy(file_path, dst_root, "_Screenshots", filename, "截圖")
            return

        is_photo = ext in ConfigConstants.EXT_PHOTOS
        is_video = ext in ConfigConstants.EXT_VIDEOS
        
        if not (is_photo or is_video):
            return

        # Deduplication
        dupe_status = self._check_duplicate(file_path, f_size)
        
        if dupe_status == "DEST_DUPE":
            self.logger.warn(f"[略過] 目標已存在: {filename}")
            with self.stats_lock:
                self.stats['skipped'] += 1
            if self.config['resume_enabled'] and not self.config.get('dry_run', False):
                self._update_history(file_path, "SKIPPED_DEST_DUPE")
                
            if self.config.get('dry_run', False):
                with self.preview_lock:
                    self.preview_log.append([file_path, "SKIP (Dest Dupe)", "-", "Target exists"])
            return
            
        elif dupe_status == "SRC_DUPE":
            if self.config['mode'] == 'copy':
                self.logger.warn(f"[略過] 來源重複檔案: {filename}")
                with self.stats_lock:
                    self.stats['skipped'] += 1
                if self.config['resume_enabled'] and not self.config.get('dry_run', False):
                    self._update_history(file_path, "SKIPPED_SRC_DUPE")
                    
                if self.config.get('dry_run', False):
                    with self.preview_lock:
                        self.preview_log.append([file_path, "SKIP (Source Dupe)", "-", "Source duplicate"])
            else:
                self._move_or_copy(file_path, dst_root, "_Duplicates", filename, "重複")
            return

        # Blur Check
        if self.config['blur_check_enabled'] and is_photo:
            is_blur, score = ImageOps.is_blurry(file_path)
            if is_blur:
                self._move_or_copy(file_path, dst_root, "_Blurry", filename, f"模糊({int(score)})")
                return

        # Date & Main Sort
        date_obj = self.date_parser.get_date(file_path, is_photo)
        
        # Live Photo Check
        is_live_photo = False
        if is_photo or is_video:
            base_p = os.path.splitext(file_path)[0]
            check_exts = ConfigConstants.EXT_VIDEOS if is_photo else ConfigConstants.EXT_PHOTOS
            for e in check_exts:
                if os.path.exists(base_p + e) or os.path.exists(base_p + e.upper()):
                    is_live_photo = True
                    break

        if date_obj:
            folder_name = date_obj.strftime("%Y-%m")
            date_prefix = date_obj.strftime("%Y_%m_%d")
            
            if is_live_photo:
                type_folder = "_LivePhotos"
            else:
                type_folder = "Photos" if is_photo else "Videos"
            
            final_sub_dir = os.path.join(type_folder, folder_name)
            
            # GPS
            if self.config['gps_enabled']:
                loc = ImageOps.get_location_folder(file_path)
                if loc: final_sub_dir = os.path.join(final_sub_dir, loc)
            
            # Rename logic
            target_dir = os.path.join(dst_root, final_sub_dir)
            
            if self.config['rename_enabled'] and not is_live_photo:
                # Use cached sequence name (Thread Safe)
                with self.naming_lock:
                    reserved = self.dry_run_paths if self.config.get('dry_run') else None
                    target_path = FSUtils.get_sequence_name(target_dir, date_prefix, ext, self.dir_counters, reserved_paths=reserved)
            else:
                if not self.config.get('dry_run'):
                    os.makedirs(target_dir, exist_ok=True)
                
                with self.naming_lock:
                    combined_path = os.path.join(target_dir, filename)
                    reserved = self.dry_run_paths if self.config.get('dry_run') else None
                    target_path = FSUtils.get_unique_path(combined_path, reserved_paths=reserved)
                
            self._execute_transfer(file_path, target_path, "整理")
            
        else:
            # No Date
            self._move_or_copy(file_path, dst_root, "No_Date", filename, "整理")

    def _move_or_copy(self, src, root, sub, name, tag):
        """Helper to move/copy to root/sub/name"""
        d = os.path.join(root, sub)
        if not self.config.get('dry_run'):
            os.makedirs(d, exist_ok=True)
        
        with self.naming_lock:
            combined_path = os.path.join(d, name)
            reserved = self.dry_run_paths if self.config.get('dry_run') else None
            t = FSUtils.get_unique_path(combined_path, reserved_paths=reserved)
            
        self._execute_transfer(src, t, tag)

    def _execute_transfer(self, src, dst, tag):
        parent = os.path.basename(os.path.dirname(dst))
        
        if self.config.get('dry_run', False):
            # Dry Run: Record Log, Don't Move
            with self.preview_lock:
                self.preview_log.append([src, f"{self.config['mode']} ({tag})", dst, "Success"])
            
            with self.naming_lock:
                self.dry_run_paths.add(dst)
                
            self.logger.info(f"[預覽-{tag}] {os.path.basename(src)} -> {parent} -> {os.path.basename(dst)}")
            
            with self.stats_lock:
                self.stats['processed'] += 1
                try: 
                    self.stats['processed_size'] += os.path.getsize(src) 
                except: pass
            return

        os.makedirs(os.path.dirname(dst), exist_ok=True)

        if self.config['mode'] == 'move':
            shutil.move(src, dst)
            self.logger.info(f"[{tag}] 移動: {os.path.basename(src)} -> {parent} -> {os.path.basename(dst)}")
        else:
            shutil.copy2(src, dst)
            self.logger.info(f"[{tag}] 複製: {os.path.basename(src)} -> {parent} -> {os.path.basename(dst)}")
            
        with self.stats_lock:
            self.stats['processed'] += 1
            try:
                self.stats['processed_size'] += os.path.getsize(dst)
            except: pass
        
        if self.config['resume_enabled']:
            self._update_history(src, dst)

    def _check_duplicate(self, path, f_size):
        """
        Return: None (Not dupe), "SRC_DUPE", "DEST_DUPE"
        Implements Tiered Hashing: Size -> Partial Hash -> Full Hash
        """
        f_partial = None
        f_full = None
        
        # 1. Check Destination Index (Global Skip)
        if self.config.get('skip_existing', False) and f_size in self.dst_index:
            candidates = self.dst_index[f_size]
            for dest_path in candidates: 
                if os.path.abspath(path) == os.path.abspath(dest_path): continue
                
                if not f_partial: f_partial = Dedup.get_partial_hash(path)
                d_partial = Dedup.get_partial_hash(dest_path)
                
                if f_partial == d_partial:
                    if not f_full: f_full = Dedup.get_hash(path)
                    d_full = Dedup.get_hash(dest_path)
                    
                    if f_full == d_full:
                        return "DEST_DUPE"

        # 2. Check Source Locally
        # Pre-compute Partial Hash (Fast, small read)
        if not f_partial: f_partial = Dedup.get_partial_hash(path)
        
        # Optimization: To maximize parallelism, we compute Full Hash OUTSIDE the lock
        # because we will likely need it anyway (to store or to compare).
        # Computing it inside the lock would serialize the process for all unique files.
        if not f_full: f_full = Dedup.get_hash(path)
        
        with self.dedup_lock:
            # Check Size
            if f_size not in self.seen_files:
                # First time seeing this size -> Unique
                self.seen_files[f_size] = {f_partial: {f_full: path}}
                return None
            
            # Check Partial
            partials = self.seen_files[f_size]
            if f_partial not in partials:
                # First time seeing this partial -> Unique
                partials[f_partial] = {f_full: path}
                return None
            
            # Partial Match -> Check Full
            fulls = partials[f_partial]
            if f_full in fulls:
                return "SRC_DUPE"
            else:
                # Full hash diff -> Collision -> Unique
                fulls[f_full] = path
                return None
                    
    # --- History Logic ---
    def _load_history(self):
        import json
        self.history_db = {}
        if os.path.exists(ConfigConstants.HISTORY_FILE):
            try:
                with open(ConfigConstants.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.history_db = json.load(f)
            except: pass

    def _save_history(self):
        import json
        try:
            with self.history_lock: # Ensure no one is writing? (Start/End is single threaded usually, but safe to lock)
                with open(ConfigConstants.HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.history_db, f) # Compact
        except: pass

    def _update_history(self, src, dst):
        try:
            mtime = os.path.getmtime(src)
            size = os.path.getsize(src)
            with self.history_lock:
                self.history_db[src] = {'mtime': mtime, 'size': size, 'dest': dst}
        except: pass

    def _is_already_processed(self, src, size):
        # Read needs lock technically if concurrent write happens? 
        # Yes, standard dict read is thread safe in python (GIL), but logic consistency?
        # Resume check happens before processing. History is mostly read-only during start... 
        # BUT _update_history writes to it.
        # So we should lock reading too.
        with self.history_lock:
            if src not in self.history_db: return False
            rec = self.history_db[src]
            
        try:
            if abs(os.path.getmtime(src) - rec['mtime']) > 2.0 or size != rec['size']: return False
            if rec['dest'] != "SKIPPED_DUPLICATE" and not os.path.exists(rec['dest']): return False
            return True
        except: return False
