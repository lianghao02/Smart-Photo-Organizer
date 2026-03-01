# -*- coding: utf-8 -*-
# ==============================================================================
# 智慧照片整理助手 (Smart Photo Organizer) v2.7
# ==============================================================================
# pip install Pillow pillow-heif geopy
# [選用] pip install xxhash opencv-python numpy reverse_geocoder
# ==============================================================================

import os
import re
import csv
import json
import hashlib
import shutil
import threading
import datetime
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Set
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

# --- 選用套件 (降級處理) ---
try:
    from PIL import Image  # type: ignore
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except ImportError:
    Image = None

try:
    import xxhash  # type: ignore
    _HAS_XXHASH = True
except ImportError:
    _HAS_XXHASH = False

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False

try:
    from geopy.geocoders import Nominatim  # type: ignore
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError  # type: ignore
    _HAS_GEOPY = True
except ImportError:
    Nominatim = None
    _HAS_GEOPY = False

try:
    import reverse_geocoder as rg  # type: ignore
    _HAS_RG = True
except ImportError:
    rg = None
    _HAS_RG = False


# ==============================================================================
# 模組一：Logger — 全域日誌單例
# ==============================================================================
class Logger:
    _instance: Optional['Logger'] = None

    def __init__(self):
        self._callback: Optional[Callable[[str, str], None]] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_callback(self, callback: Callable[[str, str], None]):
        """Callback 簽章：(message: str, level: str) -> None"""
        self._callback = callback

    def log(self, message: str, level: str = 'info'):
        cb = self._callback
        if cb is not None:
            cb(message, level)
        else:
            print(f"[{level.upper()}] {message}")

    def info(self, msg): self.log(msg, 'info')
    def warn(self, msg): self.log(msg, 'warn')
    def error(self, msg): self.log(msg, 'error')


# ==============================================================================
# 模組二：ConfigConstants + AppConfig — 設定管理
# ==============================================================================
class ConfigConstants:
    """⚙️ 全域常數 — 所有可變參數集中於此，嚴禁魔術數字"""
    APP_NAME    = "智慧照片整理助手 (Pro)"
    VERSION     = "2.7"
    CONFIG_FILE = "config.json"
    HISTORY_FILE = "history_log.json"
    BLOCK_SIZE  = 65536

    EXT_PHOTOS: Set[str] = {'.jpg', '.jpeg', '.png', '.heic', '.bmp', '.tiff', '.raw', '.arw', '.webp'}
    EXT_VIDEOS: Set[str] = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v'}
    EXT_JUNK:   Set[str] = {'.json', '.ini', '.db', '.html', '.txt', '.tmp', '.url'}
    SCREENSHOT_KEYWORDS  = ['screenshot', 'screen shot', 'captura', '螢幕擷取', '截圖', 'snapshot']


class AppConfig:
    """使用者偏好設定，以 JSON 持久化"""
    _instance: Optional['AppConfig'] = None

    def __init__(self):
        self.source_dir    = ""
        self.dest_dir      = ""
        self.skip_existing = False
        self.load()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self):
        if os.path.exists(ConfigConstants.CONFIG_FILE):
            try:
                with open(ConfigConstants.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.source_dir    = data.get('source', '')
                    self.dest_dir      = data.get('dest', '')
                    self.skip_existing = data.get('skip_existing', False)
            except Exception:
                pass

    def save(self):
        try:
            with open(ConfigConstants.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'source': self.source_dir,
                    'dest': self.dest_dir,
                    'skip_existing': self.skip_existing
                }, f, indent=4)
        except Exception as e:
            print(f"⚠️ 無法儲存設定: {e}")


# ==============================================================================
# 模組三：FSUtils — 檔案系統工具
# ==============================================================================
class FSUtils:

    @staticmethod
    def get_unique_path(path: str, reserved_paths: Optional[set] = None) -> str:
        """回傳不重複的路徑（若已存在或已預留則追加 _N）"""
        def is_taken(p: str) -> bool:
            if os.path.exists(p): return True
            if reserved_paths is not None and p in reserved_paths: return True
            return False

        if not is_taken(path):
            return path
        base, ext = os.path.splitext(path)
        counter = 1
        new_path = f"{base}_{counter}{ext}"
        while is_taken(new_path):
            counter += 1
            new_path = f"{base}_{counter}{ext}"
        return new_path

    @staticmethod
    def remove_empty_folders(path: str):
        """遞迴刪除空資料夾"""
        if not os.path.exists(path):
            return
        for root, dirs, files in os.walk(path, topdown=False):
            for name in dirs:
                d = os.path.join(root, name)
                try:
                    if not os.listdir(d):
                        os.rmdir(d)
                except Exception:
                    pass

    @staticmethod
    def get_sequence_name(target_dir: str, prefix: str, ext: str, dir_counters: dict, reserved_paths: Optional[set] = None) -> str:
        """產生 YYYY_MM_DD_001.ext 格式的序號檔名（使用計數器快取以節省 I/O）"""
        key = (target_dir, prefix)
        if key not in dir_counters:
            max_seq = 0
            if os.path.exists(target_dir):
                try:
                    pattern = re.compile(re.escape(prefix) + r'_(\d+)')
                    for fname in os.listdir(target_dir):
                        if fname.startswith(prefix + "_"):
                            match = pattern.fullmatch(os.path.splitext(fname)[0])
                            if match:
                                try:
                                    num = int(match.group(1))
                                    if num > max_seq:
                                        max_seq = num
                                except Exception:
                                    pass
                except Exception:
                    pass
            dir_counters[key] = max_seq

        current_seq = int(dir_counters[key]) + 1
        dir_counters[key] = current_seq
        while True:
            new_name = f"{prefix}_{current_seq:03d}{ext}"
            new_path = os.path.join(target_dir, new_name)
            is_reserved = False
            if reserved_paths is not None:
                is_reserved = str(new_path) in [str(p) for p in reserved_paths]
            is_taken = os.path.exists(new_path) or is_reserved
            if not is_taken:
                return new_path
            current_seq += 1
            dir_counters[key] = current_seq
        return ""


# ==============================================================================
# 模組四：Dedup — 重複檔案偵測（分層雜湊）
# ==============================================================================
class Dedup:

    @staticmethod
    def _make_hasher():
        return xxhash.xxh64() if _HAS_XXHASH else hashlib.md5()

    @staticmethod
    def get_hash(path: str) -> str:
        """計算完整檔案雜湊值"""
        hasher = Dedup._make_hasher()
        try:
            with open(path, 'rb') as f:
                while chunk := f.read(ConfigConstants.BLOCK_SIZE * 4):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    @staticmethod
    def get_partial_hash(path: str) -> str:
        """快速分段雜湊（首 + 中 + 尾各 4KB），用於預篩選"""
        try:
            size = os.path.getsize(path)
            if size < 20480:
                return f"{size}_{Dedup.get_hash(path)}"
            hasher = Dedup._make_hasher()
            with open(path, 'rb') as f:
                hasher.update(f.read(4096))
                f.seek(size // 2)
                hasher.update(f.read(4096))
                f.seek(-4096, 2)
                hasher.update(f.read(4096))
            return f"{size}_{hasher.hexdigest()}"
        except Exception:
            return ""


# ==============================================================================
# 模組五：DateParser — 多策略日期解析
# ==============================================================================
class DateParser:
    """依序嘗試：JSON Sidecar → EXIF SubIFD → EXIF 標準 → 檔名 Regex → 影片同名照片"""

    def __init__(self):
        self.logger = Logger.get_instance()

    def get_date(self, path: str, is_photo: bool) -> Optional[datetime.datetime]:
        # 1. JSON Sidecar
        try:
            for jp in [path + ".json", os.path.splitext(path)[0] + ".json"]:
                if os.path.exists(jp):
                    d = self._parse_json_date(jp)
                    if d and self._is_valid(d, f"JSON:{os.path.basename(jp)}"): return d
        except Exception:
            pass

        # 2. EXIF (照片)
        if is_photo and Image:
            d = self._get_exif_date(path)
            if d: return d

        # 3. 檔名 Regex
        d = self._parse_filename_date(os.path.basename(path))
        if d and self._is_valid(d, "Filename"): return d

        # 4. 找同名照片（影片/Live Photo 配對）
        if not is_photo:
            base = os.path.splitext(path)[0]
            for img_ext in ['.heic', '.HEIC', '.jpg', '.JPG', '.jpeg', '.JPEG']:
                sibling = base + img_ext
                if sibling != path and os.path.exists(sibling):
                    d = self.get_date(sibling, is_photo=True)
                    if d: return d
        return None

    def _get_exif_date(self, path) -> Optional[datetime.datetime]:
        if Image is None: return None
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                if not exif: return None
                # SubIFD (34665)
                if 34665 in exif:
                    try:
                        sub = exif.get_ifd(34665)
                        for tag in [36867, 36868, 306]:
                            dt_str = sub.get(tag)
                            if dt_str:
                                d = self._parse_exif_str(dt_str)
                                if d and self._is_valid(d, "Exif-SubIFD"): return d
                    except Exception:
                        pass
                # IFD0
                for tag in [36867, 306]:
                    dt_str = exif.get(tag)
                    if dt_str:
                        d = self._parse_exif_str(dt_str)
                        if d and self._is_valid(d, "Exif-IFD0"): return d
        except Exception:
            pass
        return None

    def _parse_exif_str(self, dt_str) -> Optional[datetime.datetime]:
        if not dt_str: return None
        try:
            return datetime.datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
        except Exception:
            return None

    def _parse_json_date(self, json_path) -> Optional[datetime.datetime]:
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                ts = data.get('photoTakenTime', {}).get('timestamp')
                if ts:
                    return datetime.datetime.fromtimestamp(int(ts))
        except Exception:
            pass
        return None

    def _parse_filename_date(self, filename) -> Optional[datetime.datetime]:
        m = re.search(r'(20\d{2}|19\d{2})[-_]?(\d{2})[-_]?(\d{2})', filename)
        if m:
            try:
                return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass
        m = re.search(r'(\d{13})', filename)
        if m:
            try:
                return datetime.datetime.fromtimestamp(int(m.group(1)) / 1000)
            except Exception:
                pass
        return None

    def _is_valid(self, d: datetime.datetime, src: str = "") -> bool:
        if not d or d.year < 1900: return False
        if d > datetime.datetime.now() + datetime.timedelta(days=30):
            self.logger.warn(f"⚠️ 日期異常(未來): {d} ({src}) → 歸至 No_Date")
            return False
        return True


# ==============================================================================
# 模組六：ImageOps — 模糊偵測 + GPS 地點解析
# ==============================================================================
class ImageOps:
    _geolocator = None
    _geo_cache: Dict[tuple, str] = {}

    @staticmethod
    def _init_geo():
        if ImageOps._geolocator is None and _HAS_GEOPY:
            ImageOps._geolocator = Nominatim(user_agent="smart_photo_organizer_v2", timeout=3)

    @staticmethod
    def is_blurry(path: str, threshold: float = 100.0) -> tuple[bool, float]:
        """回傳 (is_blurry, score)，使用 Laplacian Variance"""
        if not _HAS_CV2 or cv2 is None:  # type: ignore
            return False, 0.0
        try:
            arr = np.fromfile(path, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)  # type: ignore
            if img is None: return False, 0.0
            score = cv2.Laplacian(img, cv2.CV_64F).var()  # type: ignore
            return score < threshold, score
        except Exception:
            return False, 0.0

    @staticmethod
    def get_location_folder(path: str) -> Optional[str]:
        """回傳 '國家_城市' 字串，優先線上繁中，次用離線 reverse_geocoder"""
        if not Image: return None
        lat_lon = ImageOps._get_lat_lon(path)
        if not lat_lon: return None
        lat, lon = lat_lon

        if _HAS_GEOPY:
            ImageOps._init_geo()
            if ImageOps._geolocator is not None:
                cache_key = (round(float(lat), 3) if lat is not None else 0.0, 
                             round(float(lon), 3) if lon is not None else 0.0)  # type: ignore
                if cache_key in ImageOps._geo_cache:
                    return ImageOps._geo_cache[cache_key]
                try:
                    loc = ImageOps._geolocator.reverse((lat, lon), language='zh-TW', exactly_one=True)  # type: ignore
                    if loc:
                        addr = loc.raw.get('address', {})
                        country = addr.get('country', '未知國家')
                        city = addr.get('city', addr.get('county', addr.get('town', addr.get('suburb', '未知城市'))))
                        result = f"{country}_{city}"
                        ImageOps._geo_cache[cache_key] = result
                        return result
                except (GeocoderTimedOut, GeocoderServiceError, Exception):
                    pass

        if _HAS_RG and rg is not None:
            try:
                results = rg.search([lat_lon], mode=2)  # type: ignore
                if results:
                    d = results[0]
                    cc = "".join(c for c in d.get('cc', 'Unknown') if c.isalnum() or c in ' _').strip() or "Unknown"
                    nm = "".join(c for c in d.get('name', 'Location') if c.isalnum() or c in ' _').strip() or "Location"
                    return f"{cc}_{nm}"
            except Exception:
                pass
        return None

    @staticmethod
    def _get_lat_lon(path):
        if Image is None: return None
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                if not exif: return None
                gps = exif.get_ifd(34853)
                if not gps: return None
                lat_ref, lat_val = gps.get(1), gps.get(2)
                lon_ref, lon_val = gps.get(3), gps.get(4)
                if lat_val and lat_ref and lon_val and lon_ref:
                    lat = ImageOps._dms_to_deg(lat_val)
                    lon = ImageOps._dms_to_deg(lon_val)
                    if lat_ref != "N": lat = -lat
                    if lon_ref != "E": lon = -lon
                    return (lat, lon)
        except Exception:
            pass
        return None

    @staticmethod
    def _dms_to_deg(value):
        try:
            return float(value[0]) + float(value[1]) / 60.0 + float(value[2]) / 3600.0
        except Exception:
            return 0.0



# ==============================================================================
# 模組七：Processor — 核心整理引擎（多執行緒）
# ==============================================================================
class Processor:
    """
    config_options 鍵值：
      mode / clean_empty / rename_enabled / gps_enabled /
      resume_enabled / blur_check_enabled / skip_existing /
      dry_run / src_root / dst_root
    """
    def __init__(self, config_options: dict,
                 progress_callback: Any = None,
                 status_callback: Any = None):
        self.config = config_options
        self.progress_callback = progress_callback
        self.status_callback   = status_callback
        self.stop_event   = threading.Event()
        self.pause_event  = threading.Event()
        self.pause_event.set()
        self.logger      = Logger.get_instance()
        self.date_parser = DateParser()
        self.stats: Dict[str, Any] = {"processed": 0, "processed_size": 0, "total_size": 0, "skipped": 0, "errors": 0, "failed_files": []}
        self.seen_files  = {}
        self.dst_index   = {}
        self.dir_counters = {}
        self.history_db  = {}
        self.dry_run_paths = set()
        self.preview_log   = []
        self.stats_lock   = threading.Lock()
        self.history_lock = threading.Lock()
        self.naming_lock  = threading.Lock()
        self.dedup_lock   = threading.Lock()
        self.preview_lock = threading.Lock()

    def stop(self):  self.stop_event.set(); self.pause_event.set()
    def pause(self): self.pause_event.clear()
    def resume(self): self.pause_event.set()

    def start(self):
        try:
            self._load_history()
            src_root = self.config['src_root']
            dst_root = self.config['dst_root']
            mode_str = self.config['mode'].upper()
            if self.config.get('dry_run'): mode_str += " (預覽模式)"
            self.logger.info(f"🚀 開始任務\n來源: {src_root}\n目標: {dst_root}\n模式: {mode_str}")

            if self.config.get('skip_existing'):
                if self.status_callback: self.status_callback("正在建立目標索引 (去重用)...")
                self._index_destination(dst_root)
                self.logger.info(f"目標索引完成: {sum(len(v) for v in self.dst_index.values())} 檔")

            if self.status_callback: self.status_callback("正在掃描檔案...")
            all_files, total_size = self._scan_files(src_root)
            total_count = len(all_files)
            with self.stats_lock: self.stats['total_size'] = total_size

            if total_count == 0:
                self.logger.warn("⚠️ 找不到任何檔案。")
                return self.stats

            self.logger.info(f"共發現 {total_count} 個檔案 ({self._fmt(total_size)})，開始並行處理...")
            max_workers = min(32, (os.cpu_count() or 1) + 4)
            start_time  = time_start = time.time()

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Pylance: "files_list" is not defined. Assuming this was meant to be `all_files`.
                # `all_files` is already a list from `_scan_files`.
                # if not isinstance(files_list, list): files_list = list(files_list)  # type: ignore
                futures = {executor.submit(self._process_single_file, f, dst_root): f for f in all_files}
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    if self.stop_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    self.pause_event.wait()
                    completed += 1
                    cb_prog = self.progress_callback
                    if cb_prog is not None:
                        elapsed = max(time.time() - start_time, 0.001)
                        proc_sz = self.stats['processed_size']
                        speed   = proc_sz / elapsed
                        eta     = (total_size - proc_sz) / speed if speed > 0 else 0
                        if completed % 5 == 0 or completed == total_count:
                            cb_prog({'current': completed, 'total': total_count,
                                'filename': os.path.basename(str(futures[future])),
                                'processed_size': proc_sz, 'total_size': total_size,
                                'speed': speed, 'eta': eta})
                    try:
                        future.result()
                    except Exception as e:
                        with self.stats_lock:
                            self.stats['errors'] += 1
                            self.stats['failed_files'].append(f"{futures[future]}: {e}")
                        self.logger.error(f"❌ 處理失敗: {os.path.basename(futures[future])} - {e}")

            cb_prog_final = self.progress_callback
            if cb_prog_final is not None:
                cb_prog_final({'current': total_count, 'total': total_count, 'filename': 'Finished',
                    'processed_size': total_size, 'total_size': total_size, 'speed': 0, 'eta': 0})

            if not self.config.get('dry_run'): self._save_history()

            if self.config['mode'] == 'move' and self.config['clean_empty'] and not self.stop_event.is_set():
                if not self.config.get('dry_run'):
                    self.logger.info("正在清理空資料夾...")
                    FSUtils.remove_empty_folders(src_root)

            if self.config.get('dry_run'): self._export_preview_report()
            return self.stats
        except Exception as e:
            self.logger.error(f"❌ 嚴重錯誤: {e}")
            raise

    def _fmt(self, size):
        for u in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0: return f"{size:.2f} {u}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def _export_preview_report(self):
        try:
            report_path = os.path.join(os.getcwd(), "preview_report.csv")
            with open(report_path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(["Source File", "Action", "Destination File", "Note"])
                w.writerows(self.preview_log)
            self.logger.info(f"✅ 預覽報告: {report_path}")
            cb = self.status_callback
            if cb is not None: cb(f"預覽完成，請查看 {report_path}")
        except Exception as e:
            self.logger.error(f"❌ 無法寫入預覽報告: {e}")

    def _index_destination(self, dst_root):
        if not os.path.exists(dst_root): return
        count: int = 0
        cb_status = self.status_callback
        for r, d, f in os.walk(dst_root):
            if self.stop_event.is_set(): break
            for file in f:
                fp = str(os.path.join(r, file))
                try:
                    sz = int(os.path.getsize(fp))
                    if sz not in self.dst_index:
                        self.dst_index[sz] = []
                    self.dst_index[sz].append(fp)
                    c = int(count) + 1
                    count = c
                    if c % 1000 == 0 and cb_status is not None:
                        cb_status(f"正在索引目標... ({c})")
                except Exception:
                    pass

    def _scan_files(self, root):
        files_list: list[str] = []
        total_size = 0
        count: int = 0
        cb_status = self.status_callback
        for r, d, f in os.walk(root):
            if self.stop_event.is_set(): break
            for file in f:
                fp = str(os.path.join(r, file))
                files_list.append(fp)
                try: 
                    sz = int(os.path.getsize(fp))
                    total_size += sz
                except Exception: pass
                c = int(count) + 1
                count = c
                if c % 1000 == 0 and cb_status is not None:
                    cb_status(f"正在掃描... 已發現 {c} 個檔案")
        return files_list, int(total_size)

    def _process_single_file(self, file_path_raw, dst_root):
        file_path = str(file_path_raw)
        filename = str(os.path.basename(file_path))
        ext      = str(os.path.splitext(filename)[1]).lower()
        try:    f_size = os.path.getsize(file_path)
        except: f_size = 0

        if self.config['resume_enabled'] and self._is_processed(file_path, f_size):
            with self.stats_lock:
                self.stats['skipped'] += 1
                self.stats['processed_size'] += f_size
            return

        if ext in ConfigConstants.EXT_JUNK: return

        if any(kw in filename.lower() for kw in ConfigConstants.SCREENSHOT_KEYWORDS):
            self._transfer_to(file_path, dst_root, "_Screenshots", filename, "截圖"); return

        is_photo = ext in ConfigConstants.EXT_PHOTOS
        is_video = ext in ConfigConstants.EXT_VIDEOS
        if not (is_photo or is_video): return

        dupe = self._check_dup(file_path, f_size)
        if dupe == "DEST_DUPE":
            self.logger.warn(f"[略過] 目標已存在: {filename}")
            with self.stats_lock: self.stats['skipped'] += 1
            if self.config['resume_enabled'] and not self.config.get('dry_run'):
                self._hist_update(file_path, "SKIPPED_DEST_DUPE")
            if self.config.get('dry_run'):
                with self.preview_lock: self.preview_log.append([file_path, "SKIP (Dest Dupe)", "-", "Target exists"])
            return
        elif dupe == "SRC_DUPE":
            if self.config['mode'] == 'copy':
                self.logger.warn(f"[略過] 來源重複: {filename}")
                with self.stats_lock: self.stats['skipped'] += 1
                if self.config['resume_enabled'] and not self.config.get('dry_run'):
                    self._hist_update(file_path, "SKIPPED_SRC_DUPE")
                if self.config.get('dry_run'):
                    with self.preview_lock: self.preview_log.append([file_path, "SKIP (Source Dupe)", "-", "Src duplicate"])
            else:
                self._transfer_to(file_path, dst_root, "_Duplicates", filename, "重複")
            return

        if self.config['blur_check_enabled'] and is_photo:
            is_blur, score = ImageOps.is_blurry(file_path)
            if is_blur:
                self._transfer_to(file_path, dst_root, "_Blurry", filename, f"模糊({int(score)})"); return

        date_obj = self.date_parser.get_date(file_path, is_photo)

        is_live = False
        base_p = os.path.splitext(file_path)[0]
        check_exts = ConfigConstants.EXT_VIDEOS if is_photo else ConfigConstants.EXT_PHOTOS
        for e in check_exts:
            if os.path.exists(base_p + e) or os.path.exists(base_p + e.upper()):
                is_live = True; break

        if date_obj:
            type_folder  = "_LivePhotos" if is_live else ("Photos" if is_photo else "Videos")
            final_sub    = os.path.join(type_folder, date_obj.strftime("%Y-%m")) if date_obj else type_folder
            if self.config['gps_enabled']:
                loc = ImageOps.get_location_folder(file_path)
                if loc: final_sub = os.path.join(final_sub, loc)
            target_dir = os.path.join(dst_root, final_sub)
            if self.config['rename_enabled'] and not is_live:
                with self.naming_lock:
                    safe_reserved = self.dry_run_paths if self.config.get('dry_run') else set()
                    t = FSUtils.get_sequence_name(target_dir, date_obj.strftime("%Y_%m_%d") if date_obj else "Unknown", ext, self.dir_counters, safe_reserved)
            else:
                if not self.config.get('dry_run'): os.makedirs(target_dir, exist_ok=True)
                with self.naming_lock:
                    safe_reserved = self.dry_run_paths if self.config.get('dry_run') else set()
                    t = FSUtils.get_unique_path(os.path.join(target_dir, filename), safe_reserved)
            self._execute(file_path, t, "整理")
        else:
            self._transfer_to(file_path, dst_root, "No_Date", filename, "整理")

    def _transfer_to(self, src, root, sub, name, tag):
        d = os.path.join(root, sub)
        if not self.config.get('dry_run'): os.makedirs(d, exist_ok=True)
        with self.naming_lock:
            reserved = self.dry_run_paths if self.config.get('dry_run') else None
            t = FSUtils.get_unique_path(os.path.join(d, name), reserved)
        self._execute(src, t, tag)

    def _execute(self, src, dst, tag):
        parent = os.path.basename(os.path.dirname(dst))
        if self.config.get('dry_run'):
            with self.preview_lock:
                self.preview_log.append([src, f"{self.config['mode']} ({tag})", dst, "Success"])
            with self.naming_lock: self.dry_run_paths.add(dst)
            self.logger.info(f"[預覽-{tag}] {os.path.basename(src)} → {parent}/{os.path.basename(dst)}")
            with self.stats_lock:
                self.stats['processed'] += 1
                try: self.stats['processed_size'] += os.path.getsize(src)
                except Exception: pass
            return
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if self.config['mode'] == 'move':
            shutil.move(src, dst)
            self.logger.info(f"[{tag}] 移動: {os.path.basename(src)} → {parent}/{os.path.basename(dst)}")
        else:
            shutil.copy2(src, dst)
            self.logger.info(f"[{tag}] 複製: {os.path.basename(src)} → {parent}/{os.path.basename(dst)}")
        with self.stats_lock:
            self.stats['processed'] += 1
            try: self.stats['processed_size'] += os.path.getsize(dst)
            except Exception: pass
        if self.config['resume_enabled']: self._hist_update(src, dst)

    def _check_dup(self, path, f_size):
        f_p = f_f = None
        if self.config.get('skip_existing') and f_size in self.dst_index:
            for dp in self.dst_index[f_size]:
                if os.path.abspath(path) == os.path.abspath(dp): continue
                if not f_p: f_p = Dedup.get_partial_hash(path)
                if f_p == Dedup.get_partial_hash(dp):
                    if not f_f: f_f = Dedup.get_hash(path)
                    if f_f == Dedup.get_hash(dp): return "DEST_DUPE"
        if not f_p: f_p = Dedup.get_partial_hash(path)
        if not f_f: f_f = Dedup.get_hash(path)
        if f_size is None or not isinstance(f_size, int): 
            return None
        with self.dedup_lock:
            if f_size not in self.seen_files:
                self.seen_files[f_size] = {f_p: {f_f: path}}; return None
            
            partials = self.seen_files.get(f_size)
            if partials is None:
                self.seen_files[f_size] = {f_p: {f_f: path}}; return None
                
            if f_p not in partials:
                partials[f_p] = {f_f: path}; return None
                
            fulls = partials.get(f_p)
            if fulls is None:
                partials[f_p] = {f_f: path}; return None
                
            if f_f in fulls: return "SRC_DUPE"
            fulls[f_f] = path; return None

    def _load_history(self):
        self.history_db = {}
        if os.path.exists(ConfigConstants.HISTORY_FILE):
            try:
                with open(ConfigConstants.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.history_db = json.load(f)
            except Exception: pass

    def _save_history(self):
        try:
            with self.history_lock:
                with open(ConfigConstants.HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.history_db, f)
        except Exception: pass

    def _hist_update(self, src, dst):
        try:
            with self.history_lock:
                self.history_db[src] = {'mtime': os.path.getmtime(src), 'size': os.path.getsize(src), 'dest': dst}
        except Exception: pass

    def _is_processed(self, src, size):
        with self.history_lock:
            if src not in self.history_db: return False
            rec = self.history_db[src]
        try:
            if abs(os.path.getmtime(src) - rec['mtime']) > 2.0 or size != rec['size']: return False
            if rec['dest'] not in ("SKIPPED_DEST_DUPE", "SKIPPED_SRC_DUPE") and not os.path.exists(str(rec['dest'])): return False
            return True
        except Exception: return False


# ==============================================================================
# 模組八：Styles — ttk 主題樣式
# ==============================================================================
class Styles:
    @staticmethod
    def setup_styles(root):
        style = ttk.Style()
        style.theme_use('clam')
        BG      = "#F4F6F9"
        SECTION = "#FFFFFF"
        PRIMARY = "#4A90E2"
        TEXT    = "#2C3E50"
        DANGER  = "#E74C3C"
        FONT    = ("Microsoft JhengHei UI", 10)
        BOLD    = ("Microsoft JhengHei UI", 10, "bold")
        HEADER  = ("Microsoft JhengHei UI", 11, "bold")
        root.configure(bg=BG)
        style.configure("TFrame",          background=BG)
        style.configure("TLabel",          background=BG, foreground=TEXT, font=FONT)
        style.configure("Section.TFrame",  background=SECTION)
        style.configure("Section.TLabel",  background=SECTION, foreground=TEXT, font=FONT)
        style.configure("TLabelframe",     background=SECTION, bordercolor="#DCE1E7", borderwidth=1)
        style.configure("TLabelframe.Label", background=SECTION, foreground=PRIMARY, font=HEADER)
        style.configure("TButton",         font=BOLD, borderwidth=0, focuscolor="none", padding=8, background="#E0E6ED", foreground=TEXT)
        style.map("TButton", background=[('active', PRIMARY), ('disabled', '#D0D0D0')], foreground=[('active', 'white'), ('disabled', '#888')])
        style.configure("Primary.TButton", background=PRIMARY, foreground="white")
        style.map("Primary.TButton",       background=[('active', '#357ABD')])
        style.configure("Danger.TButton",  background=DANGER, foreground="white")
        style.map("Danger.TButton",        background=[('active', '#C0392B')])
        style.configure("TEntry",          padding=5, bordercolor=PRIMARY)
        style.configure("TCheckbutton",    background=SECTION, font=FONT, focuscolor="none")
        style.configure("TRadiobutton",    background=SECTION, font=FONT, focuscolor="none")
        style.configure("Horizontal.TProgressbar", troughcolor="#E0E0E0", background=PRIMARY, bordercolor=BG, lightcolor=PRIMARY, darkcolor=PRIMARY)


# ==============================================================================
# 模組九：MainWindow — tkinter 主視窗
# ==============================================================================
class MainWindow:
    def __init__(self, root):
        self.root       = root
        self.app_config = AppConfig.get_instance()
        self.logger     = Logger.get_instance()
        self.root.title(f"{ConfigConstants.APP_NAME} v{ConfigConstants.VERSION}")
        self.root.geometry("950x750")

        self.source_dir        = tk.StringVar(value=self.app_config.source_dir)
        self.dest_dir          = tk.StringVar(value=self.app_config.dest_dir)
        self.mode              = tk.StringVar(value="copy")
        self.clean_empty       = tk.BooleanVar(value=False)
        self.rename_enabled    = tk.BooleanVar(value=False)
        self.gps_enabled       = tk.BooleanVar(value=False)
        self.resume_enabled    = tk.BooleanVar(value=True)
        self.blur_check_enabled = tk.BooleanVar(value=False)
        self.skip_existing     = tk.BooleanVar(value=bool(self.app_config.skip_existing))
        self.dry_run           = tk.BooleanVar(value=False)
        self.processor: Any    = None
        
        self.chk_clean: Any = None
        self.btn_start: Any = None
        self.btn_pause: Any = None
        self.btn_stop: Any  = None
        self.lbl_stats: Any = None
        self.lbl_speed: Any = None
        self.lbl_eta: Any   = None
        self.lbl_size_prog: Any = None
        self.progress: Any  = None
        self.lbl_current: Any = None
        self.log_area: Any  = None

        self.logger.set_callback(self._on_log)
        Styles.setup_styles(self.root)
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill="both", expand=True)
        # Header
        h = ttk.Frame(container); h.pack(fill="x", pady=(0, 15))
        ttk.Label(h, text="✨ " + ConfigConstants.APP_NAME,
                  font=("Microsoft JhengHei UI", 16, "bold"), foreground="#2C3E50").pack(side="left")
        ttk.Label(h, text=f"v{ConfigConstants.VERSION}",
                  font=("Segoe UI", 10), foreground="#7F8C8D").pack(side="left", padx=10, pady=(8, 0))
        self._build_paths(container)
        self._build_options(container)
        self._build_controls(container)
        self._build_log(container)

    def _build_paths(self, parent):
        f = ttk.LabelFrame(parent, text=" 📂 資料夾路徑設定 ", padding=15)
        f.pack(fill="x", pady=10)
        ttk.Label(f, text="來源資料夾:", style="Section.TLabel").grid(row=0, column=0, padx=5, pady=8, sticky='w')
        ttk.Entry(f, textvariable=self.source_dir, width=65).grid(row=0, column=1, padx=5, pady=8)
        ttk.Button(f, text="瀏覽...", command=self._sel_src).grid(row=0, column=2, padx=5, pady=8)
        ttk.Label(f, text="目標資料夾:", style="Section.TLabel").grid(row=1, column=0, padx=5, pady=8, sticky='w')
        ttk.Entry(f, textvariable=self.dest_dir, width=65).grid(row=1, column=1, padx=5, pady=8)
        ttk.Button(f, text="瀏覽...", command=self._sel_dst).grid(row=1, column=2, padx=5, pady=8)

    def _build_options(self, parent):
        f = ttk.LabelFrame(parent, text=" ⚙️ 整理規則與選項 ", padding=15)
        f.pack(fill="x", pady=10)
        mf = ttk.Frame(f); mf.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(mf, text="運作模式:", font=("Microsoft JhengHei UI", 10, "bold")).pack(side="left", padx=(5, 15))
        ttk.Radiobutton(mf, text="複製 (Copy) - 保留原始", variable=self.mode, value="copy").pack(side="left", padx=10)
        ttk.Radiobutton(mf, text="移動 (Move) - 原始將被移走", variable=self.mode, value="move",
                        command=self._toggle_clean).pack(side="left", padx=10)
        tip = "💡 效能提示：\n   • 移動：同磁碟極快；複製：異磁碟最快"
        ttk.Label(f, text=tip, foreground="#7F8C8D", font=("Segoe UI", 9)).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 10))
        ttk.Separator(f, orient='horizontal').grid(row=2, column=0, columnspan=3, sticky="ew", pady=5)

        ttk.Checkbutton(f, text="標準化重命名 (YYYY_MM_DD_流水號)", variable=self.rename_enabled).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        ttk.Checkbutton(f, text="跳過目標已存在的檔案 (去重)", variable=self.skip_existing).grid(row=3, column=1, sticky="w", padx=10, pady=5)
        self.chk_clean = ttk.Checkbutton(f, text="刪除來源空資料夾 (僅移動模式)", variable=self.clean_empty)
        self.chk_clean.grid(row=3, column=2, sticky="w", padx=10, pady=5)
        ttk.Checkbutton(f, text="啟用 GPS 地點分類", variable=self.gps_enabled).grid(row=4, column=0, sticky="w", padx=10, pady=5)
        ttk.Checkbutton(f, text="啟用斷點續傳",       variable=self.resume_enabled).grid(row=4, column=1, sticky="w", padx=10, pady=5)
        ttk.Checkbutton(f, text="模糊偵測 (實驗性)",   variable=self.blur_check_enabled).grid(row=4, column=2, sticky="w", padx=10, pady=5)
        ttk.Separator(f, orient='horizontal').grid(row=5, column=0, columnspan=3, sticky="ew", pady=10)

        chk_dry = tk.Checkbutton(f, text="✨ 模擬執行 (預覽模式) — 僅產報表，不寫入硬碟",
                       variable=self.dry_run, font=("Microsoft JhengHei UI", 10, "bold"),
                       bg='#e8f5e9', fg='#2e7d32', selectcolor='#e8f5e9',
                       activebackground='#c8e6c9', activeforeground='#2e7d32', padx=10, pady=5, relief="flat")
        chk_dry.grid(row=6, column=0, columnspan=3, sticky="w", padx=5)
        for col in range(3): f.columnconfigure(col, weight=1)
        self._toggle_clean()

    def _build_controls(self, parent):
        f = ttk.Frame(parent); f.pack(fill="x", pady=15)
        bf = ttk.Frame(f); bf.pack(side="left")
        self.btn_start = ttk.Button(bf, text="▶ 開始整理", command=self._start, style="Primary.TButton", width=15)
        self.btn_start.pack(side="left", padx=(0, 10))
        self.btn_pause = ttk.Button(bf, text="⏸ 暫停", command=self._toggle_pause, state="disabled", width=10)
        self.btn_pause.pack(side="left", padx=10)
        self.btn_stop  = ttk.Button(bf, text="⏹ 停止", command=self._stop, state="disabled", style="Danger.TButton", width=10)
        self.btn_stop.pack(side="left", padx=10)
        self.lbl_stats = ttk.Label(f, text="準備就緒", font=("Microsoft JhengHei UI", 11), foreground="#4A90E2")
        self.lbl_stats.pack(side="right", padx=10, fill="y")

    def _build_log(self, parent):
        f = ttk.LabelFrame(parent, text=" 📊 即時監控儀表板 ", padding=15)
        f.pack(fill="both", expand=True, pady=(0, 5))
        dash = ttk.Frame(f); dash.pack(fill="x", pady=(0, 10))
        def card(title, col):
            fc = ttk.Frame(dash, borderwidth=1, relief="solid", padding=10)
            fc.grid(row=0, column=col, padx=5, sticky="ew")
            dash.columnconfigure(col, weight=1)
            ttk.Label(fc, text=title, font=("Segoe UI", 9), foreground="#7F8C8D").pack()
            v = ttk.Label(fc, text="-", font=("Consolas", 14, "bold"), foreground="#2C3E50")
            v.pack()
            return v
        self.lbl_speed    = card("傳輸速度", 0)
        self.lbl_eta      = card("預估剩餘時間", 1)
        self.lbl_size_prog = card("處理容量進度", 2)
        self.progress = ttk.Progressbar(f, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 5))
        self.lbl_current = ttk.Label(f, text="等待開始...", font=("Microsoft JhengHei UI", 9), foreground="#7F8C8D")
        self.lbl_current.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text="執行日誌:", font=("Microsoft JhengHei UI", 9, "bold")).pack(anchor="w")
        self.log_area = scrolledtext.ScrolledText(f, state='disabled', height=8, font=("Consolas", 10), bg="#FAFAFA", relief="flat", padx=10, pady=10)
        self.log_area.pack(fill="both", expand=True)
        self.log_area.tag_config('error', foreground='#E74C3C')
        self.log_area.tag_config('warn',  foreground='#D35400')

    # --- 事件處理 ---
    def _on_progress(self, data):
        self.root.after(0, lambda: self._update_progress(data))

    def _update_progress(self, data):
        total = int(data['total'])
        if total > 0 and self.progress is not None: self.progress.configure(value=(float(data['current']) / total) * 100)
        if self.lbl_current is not None: self.lbl_current.configure(text=f"正在處理: {data['filename']}")
        if self.lbl_stats is not None: self.lbl_stats.configure(text=f"進度: {data['current']}/{total}")
        try:
            s = float(data['speed']) / (1024 * 1024)
            if self.lbl_speed is not None: self.lbl_speed.configure(text=f"{s:.1f} MB/s")
            eta = int(data['eta'])
            m, s_time = divmod(eta, 60)
            h, m = divmod(m, 60)
            if self.lbl_eta is not None: self.lbl_eta.configure(text=(f"{h}h {m}m" if h > 0 else f"{m}m {s_time}s"))
            ps = self._fmt_size(float(data['processed_size']))
            ts = self._fmt_size(float(data['total_size']))
            if self.lbl_size_prog is not None: self.lbl_size_prog.configure(text=f"{ps} / {ts}")
        except Exception: pass

    def _fmt_size(self, size):
        for u in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0: return f"{size:.1f} {u}"
            size /= 1024.0
        return f"{size:.1f} PB"

    def _on_status(self, msg): 
        self.root.after(0, lambda: self.lbl_stats.configure(text=msg) if self.lbl_stats else None)
    def _toggle_clean(self):
        if self.chk_clean is not None:
            (self.chk_clean.state(['!disabled']) if self.mode.get() == 'move'
             else (self.chk_clean.state(['disabled']), self.clean_empty.set(False)))
    def _sel_src(self):
        p = filedialog.askdirectory()
        if p: self.source_dir.set(str(Path(p).absolute()))
    def _sel_dst(self):
        p = filedialog.askdirectory()
        if p: self.dest_dir.set(str(Path(p).absolute()))

    def _on_log(self, msg, level):
        def _append():
            if self.log_area is not None:
                self.log_area.configure(state='normal')
                tag = 'error' if level == 'error' else ('warn' if level == 'warn' else '')
                prefix = "[錯誤] " if level == 'error' else ("[跳過] " if level == 'warn' else "")
                self.log_area.insert(tk.END, f"{prefix}{msg}\n", tag)
                self.log_area.see(tk.END)
                self.log_area.configure(state='disabled')
        self.root.after(0, _append)

    def _start(self):
        src, dst = self.source_dir.get(), self.dest_dir.get()
        if not src or not os.path.exists(src):
            messagebox.showerror("錯誤", "來源資料夾無效！"); return
        if not dst or not os.path.exists(dst):
            messagebox.showerror("錯誤", "目標資料夾無效！"); return
        self.app_config.source_dir    = src
        self.app_config.dest_dir      = dst
        self.app_config.skip_existing = self.skip_existing.get()
        self.app_config.save()
        opts = {
            'mode': self.mode.get(), 'clean_empty': self.clean_empty.get(),
            'rename_enabled': self.rename_enabled.get(), 'gps_enabled': self.gps_enabled.get(),
            'resume_enabled': self.resume_enabled.get(), 'blur_check_enabled': self.blur_check_enabled.get(),
            'skip_existing': self.skip_existing.get(), 'dry_run': self.dry_run.get(),
            'src_root': src, 'dst_root': dst
        }
        if self.log_area is not None:
            self.log_area.configure(state='normal')
            self.log_area.delete('1.0', tk.END)
            self.log_area.configure(state='disabled')
        self._set_ui_state(True)
        self.processor = Processor(opts, progress_callback=self._on_progress, status_callback=self._on_status)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            r = self.processor.start()
            self._on_log("=== ✅ 任務完成 ===", "info")
            msg = f"整理完成！\n已處理: {r['processed']}\n跳過: {r['skipped']}\n錯誤: {r['errors']}"
            self.root.after(0, lambda: messagebox.showinfo("完成", msg))
        except Exception as e:
            self._on_log(f"❌ 執行中斷: {e}", "error")
        finally:
            self.root.after(0, lambda: self._set_ui_state(False))

    def _toggle_pause(self):
        if not self.processor: return
        paused = self.btn_pause.cget('text') == "▶ 繼續"
        if paused:
            self.processor.resume()
            self.btn_pause.configure(text="⏸ 暫停")
            self._on_log(">> ▶️ 任務繼續", "info")
        else:
            self.processor.pause()
            self.btn_pause.configure(text="▶ 繼續")
            self._on_log(">> ⏸ 任務已暫停", "warn")

    def _stop(self):
        if not self.processor: return
        if messagebox.askyesno("確認", "確定要停止目前的任務嗎？"):
            self.processor.stop()
            self._on_log(">> ⏹ 正在停止任務...", "warn")

    def _set_ui_state(self, running: bool):
        if self.btn_start: self.btn_start.configure(state='disabled' if running else 'normal')
        if self.btn_pause: self.btn_pause.configure(state='normal' if running else 'disabled')
        if self.btn_stop: self.btn_stop.configure(state='normal' if running else 'disabled')

    def _on_close(self):
        if self.processor: self.processor.stop()
        self.app_config.save()
        self.root.destroy()


# ==============================================================================
# 程式入口
# ==============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app  = MainWindow(root)
    root.mainloop()

