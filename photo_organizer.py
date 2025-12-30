
# -*- coding: utf-8 -*-
import os
import shutil
import datetime
import threading
import hashlib
import json
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
from pathlib import Path

# --- 依賴庫安裝說明 (Dependencies) ---
# 請務必安裝以下套件以支援圖片處理與 HEIC 格式:
# pip install Pillow pillow-heif

try:
    from PIL import Image, ExifTags
    import pillow_heif
    # 註冊 HEIC Opener
    pillow_heif.register_heif_opener()
except ImportError:
    Image = None
    print("警告: 未安裝 Pillow 或 pillow-heif，部分圖片功能可能失效。")

# --- 設定常數 (Configuration Constants) ---
class CONFIG:
    APP_NAME = "專業照片整理助手 (Pro)"
    VERSION = "2.0"
    CONFIG_FILE = "config.json"
    BLOCK_SIZE = 65536  # Hash 讀取區塊大小
    
    # 支援的副檔名
    EXT_PHOTOS = {'.jpg', '.jpeg', '.png', '.heic', '.bmp', '.tiff', '.raw', '.arw', '.webp'}
    EXT_VIDEOS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v'}
    EXT_JUNK = {'.json', '.ini', '.db', '.html', '.txt', '.tmp', '.url'}

class PhotoOrganizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{CONFIG.APP_NAME} v{CONFIG.VERSION}")
        self.root.geometry("950x750")
        
        # --- 狀態變數 ---
        self.source_dir = tk.StringVar()
        self.dest_dir = tk.StringVar()
        self.mode = tk.StringVar(value="copy")  # copy or move
        self.clean_empty = tk.BooleanVar(value=False)
        self.rename_enabled = tk.BooleanVar(value=False) # 預設關閉重命名
        
        self.is_running = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set() # 預設為 Set (非暫停狀態)

        # 統計變數
        self.stats = {
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "failed_files": []
        }

        # 設定樣式
        self._setup_styles()
        # 建立介面
        self._create_widgets()
        # 載入設定
        self._load_config()
        # 關閉時儲存設定
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#f0f0f0")
        style.configure("TLabel", background="#f0f0f0", font=("Microsoft JhengHei", 10))
        style.configure("TButton", font=("Microsoft JhengHei", 10))
        style.configure("Header.TLabel", font=("Microsoft JhengHei", 11, "bold"))

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill="both", expand=True)

        # 1. 檔案路徑設定區
        self._create_path_section(main_frame)
        
        # 2. 選項設定區
        self._create_options_section(main_frame)
        
        # 3. 控制按鈕區
        self._create_control_section(main_frame)
        
        # 4. 訊息與日誌區
        self._create_log_section(main_frame)

    def _create_path_section(self, parent):
        frame = ttk.LabelFrame(parent, text="📂 資料夾路徑設定", padding=10)
        frame.pack(fill="x", pady=5)
        
        # 來源
        ttk.Label(frame, text="來源資料夾 (Source):").grid(row=0, column=0, sticky="w", padx=5)
        ttk.Entry(frame, textvariable=self.source_dir, width=70).grid(row=0, column=1, padx=5)
        ttk.Button(frame, text="瀏覽...", command=self._select_source).grid(row=0, column=2, padx=5)
        
        # 目標
        ttk.Label(frame, text="目標資料夾 (Target):").grid(row=1, column=0, sticky="w", padx=5)
        ttk.Entry(frame, textvariable=self.dest_dir, width=70).grid(row=1, column=1, padx=5)
        ttk.Button(frame, text="瀏覽...", command=self._select_dest).grid(row=1, column=2, padx=5)

    def _create_options_section(self, parent):
        frame = ttk.LabelFrame(parent, text="⚙️ 操作設定", padding=10)
        frame.pack(fill="x", pady=5)
        
        # 模式選擇
        ttk.Radiobutton(frame, text="複製 (安全模式) - 保留原始檔案", variable=self.mode, value="copy").pack(anchor="w")
        ttk.Radiobutton(frame, text="移動 (整理模式) - 完成後移動檔案", variable=self.mode, value="move", command=self._toggle_clean_option).pack(anchor="w")
        
        # 進階選項
        self.chk_clean = ttk.Checkbutton(frame, text="移動後刪除來源空資料夾", variable=self.clean_empty)
        self.chk_clean.pack(anchor="w", padx=20)
        
        self.chk_rename = ttk.Checkbutton(frame, text="同時重命名檔案 (YYYY_MM_DD_流水號)", variable=self.rename_enabled)
        self.chk_rename.pack(anchor="w", padx=20)
        
        self._toggle_clean_option() # 初始化狀態

    def _create_control_section(self, parent):
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="x", pady=5)
        
        self.btn_start = ttk.Button(frame, text="▶ 開始整理", command=self._start_thread)
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_pause = ttk.Button(frame, text="⏸ 暫停", command=self._toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=5)
        
        self.btn_stop = ttk.Button(frame, text="⏹ 停止", command=self._stop_process, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        
        # 狀態統計
        self.lbl_stats = ttk.Label(frame, text="等待開始...", font=("Microsoft JhengHei", 10, "bold"), foreground="#007acc")
        self.lbl_stats.pack(side="right", padx=5)

    def _create_log_section(self, parent):
        frame = ttk.LabelFrame(parent, text="📝 操作日誌與狀態", padding=10)
        frame.pack(fill="both", expand=True, pady=5)
        
        # 進度條
        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", pady=(0, 10))
        
        # Log
        self.log_area = scrolledtext.ScrolledText(frame, state='disabled', height=10, font=("Consolas", 9))
        self.log_area.pack(fill="both", expand=True)

    # --- 邏輯功能實作 ---

    def _toggle_clean_option(self):
        if self.mode.get() == 'move':
            self.chk_clean.state(['!disabled'])
        else:
            self.chk_clean.state(['disabled'])
            self.clean_empty.set(False)

    def _select_source(self):
        p = filedialog.askdirectory()
        if p: self.source_dir.set(str(Path(p).absolute()))

    def _select_dest(self):
        p = filedialog.askdirectory()
        if p: self.dest_dir.set(str(Path(p).absolute()))

    def _log(self, msg, tag=None):
        def _append():
            self.log_area.configure(state='normal')
            if tag == 'error':
                self.log_area.insert(tk.END, f"[錯誤] {msg}\n", 'error')
            elif tag == 'warn':
                self.log_area.insert(tk.END, f"[跳過] {msg}\n", 'warn')
            else:
                self.log_area.insert(tk.END, f"{msg}\n")
            self.log_area.see(tk.END)
            self.log_area.configure(state='disabled')
        if self.root:
            self.root.after(0, _append)

    def _update_ui_state(self, running):
        state = 'disabled' if running else 'normal'
        inv_state = 'normal' if running else 'disabled'
        
        self.btn_start.configure(state=state)
        self.btn_pause.configure(state=inv_state)
        self.btn_stop.configure(state=inv_state)
        
        # 路徑設定在執行中鎖定
        # (略作簡化，可擴充)

    def _start_thread(self):
        src = self.source_dir.get()
        dst = self.dest_dir.get()
        
        if not src or not os.path.exists(src):
            messagebox.showerror("錯誤", "來源資料夾無效！")
            return
        if not dst or not os.path.exists(dst):
            messagebox.showerror("錯誤", "目標資料夾無效！")
            return
            
        self.is_running = True
        self.stop_event.clear()
        self.pause_event.set()
        self.is_paused = False
        
        # 重置統計
        self.stats = {"processed": 0, "skipped": 0, "errors": 0, "failed_files": []}
        # 重置去重資料庫 {filesize: {set of hashes}}
        self.seen_files = {}
        # 重置目錄編號快取 {(dir_path, prefix): max_seq}
        self.dir_counters = {}
        self.log_area.configure(state='normal')
        self.log_area.delete('1.0', tk.END)
        self.log_area.tag_config('error', foreground='red')
        self.log_area.tag_config('warn', foreground='#808000') # Dark Yellow
        self.log_area.configure(state='disabled')
        
        self._update_ui_state(True)
        self._log(f"=== 開始任務 ===\n來源: {src}\n目標: {dst}\n模式: {self.mode.get().upper()}")
        
        threading.Thread(target=self._process_pipeline, args=(src, dst), daemon=True).start()

    def _toggle_pause(self):
        if self.is_paused:
            self.pause_event.set()
            self.is_paused = False
            self.btn_pause.configure(text="⏸ 暫停")
            self._log(">> 任務繼續")
        else:
            self.pause_event.clear()
            self.is_paused = True
            self.btn_pause.configure(text="▶ 繼續")
            self._log(">> 任務已暫停")

    def _stop_process(self):
        if messagebox.askyesno("確認", "確定要停止目前的任務嗎？"):
            self.stop_event.set()
            self.pause_event.set() # 確保若在暫停中也能跳出
            self._log(">> 正在停止任務...")

    def _process_pipeline(self, src_root, dst_root):
        try:
            # 1. 掃描檔案
            self._log("正在掃描檔案...", None)
            all_files = []
            for r, d, f in os.walk(src_root):
                for file in f:
                    all_files.append(os.path.join(r, file))
            
            total = len(all_files)
            if total == 0:
                self._log("找不到任何檔案。", 'warn')
                self._finish_tasks()
                return

            self._log(f"共發現 {total} 個檔案。開始處理...")
            
            # 2. 逐一處理
            for idx, file_path in enumerate(all_files):
                if self.stop_event.is_set():
                    break
                
                self.pause_event.wait() # 暫停控制
                
                # 更新 UI
                if idx % 5 == 0: # 降低更新頻率以提升效能
                    prog = ((idx) / total) * 100
                    self.root.after(0, lambda v=prog: self.progress.configure(value=v))
                    self._update_stats_label()

                try:
                    self._handle_single_file(file_path, dst_root)
                except Exception as e:
                    self.stats['errors'] += 1
                    self.stats['failed_files'].append(f"{file_path} (例外錯誤: {str(e)})")
                    self._log(f"處理失敗: {os.path.basename(file_path)} - {e}", 'error')

            # 3. 清理空資料夾 (Move 模式)
            if self.mode.get() == 'move' and self.clean_empty.get() and not self.stop_event.is_set():
                self._log("正在清理空資料夾...")
                self._remove_empty_folders(src_root)

            # 4. 生成報告
            self._generate_report(dst_root)
            
            self._log("=== 任務完成 ===")
            messagebox.showinfo("完成", f"整理完成！\n已處理: {self.stats['processed']}\n跳過: {self.stats['skipped']}\n錯誤: {self.stats['errors']}")

        except Exception as e:
            self._log(f"嚴重錯誤: {e}", 'error')
            messagebox.showerror("嚴重錯誤", str(e))
        finally:
            self._finish_tasks()

    def _handle_single_file(self, file_path, dst_root):
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        
        # A. 雜檔過濾
        if ext in CONFIG.EXT_JUNK:
            return 

        # B. 截圖隔離 (Screenshot Isolation)
        SCREENSHOT_KEYWORDS = ['screenshot', 'screen shot', 'captura', '螢幕擷取', '截圖', 'snapshot']
        if any(kw in filename.lower() for kw in SCREENSHOT_KEYWORDS):
            target_dir = os.path.join(dst_root, "_Screenshots")
            os.makedirs(target_dir, exist_ok=True)
            # 截圖保留原檔名，但需處理同名衝突
            target_path = os.path.join(target_dir, filename)
            target_path = self._get_unique_path(target_path)
            self._execute_action(file_path, target_path, "截圖")
            return

        is_photo = ext in CONFIG.EXT_PHOTOS
        is_video = ext in CONFIG.EXT_VIDEOS
        
        if not (is_photo or is_video):
            return 

        # C. 全域去重 (Global Deduplication)
        # 為了效能，先比對檔案大小，有命中才算 Hash
        f_size = os.path.getsize(file_path)
        is_duplicate = False
        original_file = None
        
        if f_size in self.seen_files:
            # 大小相同，檢查 Hash
            f_hash = self._get_hash(file_path)
            # seen_files結構調整為: {size: {hash: first_file_path}}
            if f_hash in self.seen_files[f_size]:
                is_duplicate = True
                original_file = self.seen_files[f_size][f_hash]
            else:
                self.seen_files[f_size][f_hash] = file_path
        else:
            # 新的大小，記錄起來
            f_hash = self._get_hash(file_path)
            self.seen_files[f_size] = {f_hash: file_path}
            
        if is_duplicate:
            target_dir = os.path.join(dst_root, "_Duplicates")
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, filename)
            target_path = self._get_unique_path(target_path)
            
            # 在日誌中註記「與誰重複」
            dup_msg = f"重複 (原始檔: {os.path.basename(original_file)})"
            self._execute_action(file_path, target_path, dup_msg)
            self.stats['skipped'] += 1 
            return

        # D. 取得日期 -> 決定資料夾
        date_obj = self._get_date(file_path, is_photo)

        # Check Live Photo Pair (原況照片偵測)
        is_live_photo = False
        if is_photo or is_video:
            base_p = os.path.splitext(file_path)[0]
            # 檢查是否存在對應的配對檔
            # 若是 Photo，找 Video; 若是 Video，找 Photo
            check_exts = CONFIG.EXT_VIDEOS if is_photo else CONFIG.EXT_PHOTOS
            for e in check_exts:
                if os.path.exists(base_p + e) or os.path.exists(base_p + e.upper()):
                    is_live_photo = True
                    break

        if date_obj:
            folder_name = date_obj.strftime("%Y-%m")
            date_prefix = date_obj.strftime("%Y_%m_%d")
            
            if is_live_photo:
                # Live Photos 獨立分類
                type_folder = "_LivePhotos"
            else:
                type_folder = "Photos" if is_photo else "Videos"
                
            target_dir = os.path.join(dst_root, type_folder, folder_name)
            os.makedirs(target_dir, exist_ok=True)
            
            # 有日期 -> 檢查是否啟用重命名
            # 注意: Live Photos 強制「保留原檔名」以確保照片與影片能配對成功 (因為重命名可能會導致序號不一致)
            if self.rename_enabled.get() and not is_live_photo:
                target_path = self._get_sequence_name(target_dir, date_prefix, ext)
            else:
                target_path = os.path.join(target_dir, filename)
                target_path = self._get_unique_path(target_path)
        else:
            # 無日期 -> No_Date 資料夾 -> 保留原檔名
            folder_name = "No_Date"
            target_dir = os.path.join(dst_root, folder_name)
            os.makedirs(target_dir, exist_ok=True)
            
            target_path = os.path.join(target_dir, filename)
            target_path = self._get_unique_path(target_path)

        # E. 執行動作
        self._execute_action(file_path, target_path, "整理")
        self.stats['processed'] += 1

    def _execute_action(self, src, dst, log_tag):
        # 取得父資料夾名稱 (e.g., 2021-10)
        parent_folder = os.path.basename(os.path.dirname(dst))
        
        if self.mode.get() == 'move':
            shutil.move(src, dst)
            self._log(f"[{log_tag}] 移動: {os.path.basename(src)} -> {parent_folder} -> {os.path.basename(dst)}")
        else:
            shutil.copy2(src, dst)
            self._log(f"[{log_tag}] 複製: {os.path.basename(src)} -> {parent_folder} -> {os.path.basename(dst)}")

    def _get_sequence_name(self, target_dir, prefix, ext):
        """
        產生 YYYY_MM_DD_001.ext 格式的檔名
        效能優化 (v2): 快取每個目錄+日期的最大流水號，
        直接從 (max + 1) 開始，避免 O(N^2) 的重複 os.path.exists 檢查
        """
        key = (target_dir, prefix)
        
        # 1. 若該目錄+日期未被掃描過，先掃描一次找出目前最大號碼
        if key not in self.dir_counters:
            max_seq = 0
            if os.path.exists(target_dir):
                # 掃描該目錄下所有檔案
                import re
                try:
                    # Pattern: prefix_(\d+).ext (e.g., 2021_09_26_042.jpg)
                    # 注意: prefix 本身可能含底線
                    # 這裡簡化檢查：檔名開頭符合 prefix_，且後面接數字
                    pattern = re.compile(re.escape(prefix) + r'_(\d+)')
                    
                    for fname in os.listdir(target_dir):
                        # 只看開頭符合的
                        if fname.startswith(prefix + "_"):
                            # 嘗試解析數字
                            base_name = os.path.splitext(fname)[0]
                            match = pattern.fullmatch(base_name)
                            if match:
                                try:
                                    num = int(match.group(1))
                                    if num > max_seq:
                                        max_seq = num
                                except:
                                    pass
                except Exception:
                    pass
            self.dir_counters[key] = max_seq

        # 2. 取號並遞增
        current_seq = self.dir_counters[key] + 1
        self.dir_counters[key] = current_seq
        
        # 3. 確保檔案不存在 (雙重保險，防止多人操作或掃描不完全)
        # 正常情況下第一次就不會存在，只會執行一次 O(1)
        while True:
            new_name = f"{prefix}_{current_seq:03d}{ext}"
            new_path = os.path.join(target_dir, new_name)
            if not os.path.exists(new_path):
                return new_path
            
            # 撞名了 (極少見)，繼續嘗試下一個
            current_seq += 1
            self.dir_counters[key] = current_seq

    def _parse_filename_date(self, filename):
        """
        從檔名解析日期 (Regex)
        支援: 20210310, 2021-03-10, 2021_03_10, 1614212345 (Timestamp)
        """
        import re
        # Pattern 1: YYYYMMDD (e.g. VID20210310...)
        # 排除 19xxx 20xxx 等年份，避免誤判
        match = re.search(r'(20\d{2}|19\d{2})[-_]?(\d{2})[-_]?(\d{2})', filename)
        if match:
            try:
                y, m, d = match.groups()
                return datetime.datetime(int(y), int(m), int(d))
            except:
                pass
        
        # Pattern 2: Timestamp (13 digits usually for ms, 10 for sec) - Google Photos 有時用 timestamp
        match_ts = re.search(r'(\d{13})', filename) # 毫秒級
        if match_ts:
            try:
                ts = int(match_ts.group(1)) / 1000
                return datetime.datetime.fromtimestamp(ts)
            except:
                pass

        return None

    def _get_date(self, path, is_photo):
        # 1. JSON Sidecar (Google Takeout 優先)
        try:
            json_path = path + ".json"
            if os.path.exists(json_path):
                date = self._parse_json_date(json_path)
                if date: return date
            
            base_name = os.path.splitext(path)[0]
            json_path_2 = base_name + ".json"
            if os.path.exists(json_path_2):
                 date = self._parse_json_date(json_path_2)
                 if date: return date
        except:
            pass

        # 2. Image EXIF (Deep Scan)
        if is_photo and Image:
            try:
                img_to_close = None
                try:
                    img = Image.open(path)
                    img_to_close = img
                    
                    exif = img.getexif()
                    if exif:
                        # 策略調整：優先讀取 SubIFD (0x8769)，因為詳細的 DateTimeOriginal 通常藏在這裡
                        # 且 IFD0 的 306 (DateTime) 往往是「修改時間」而非「拍攝時間」
                        
                        # 1. Check SubIFD (0x8769 / 34665)
                        if 34665 in exif:
                            try:
                                sub_exif = exif.get_ifd(34665)
                                # 優先找 DateTimeOriginal (36867)
                                dt_str = sub_exif.get(36867)
                                if dt_str: return self._parse_exif_date(dt_str)
                                # 其次找 DateTimeDigitized (36868)
                                dt_str = sub_exif.get(36868)
                                if dt_str: return self._parse_exif_date(dt_str)
                                # 最後才找 DateTime (306)
                                dt_str = sub_exif.get(306)
                                if dt_str: return self._parse_exif_date(dt_str)
                            except:
                                pass

                        # 2. Check IFD0 (Standard Tags)
                        # DateTimeOriginal (36867)
                        dt_str = exif.get(36867)
                        if dt_str: return self._parse_exif_date(dt_str)
                        
                        # DateTime (306) - 這是最後的 fallback，通常是修改時間
                        dt_str = exif.get(306)
                        if dt_str: return self._parse_exif_date(dt_str)
                            
                except Exception:
                    pass
                finally:
                    if img_to_close: img_to_close.close()
            except:
                pass
        
        # 3. Filename Regex (New Strategy: Parse Filename)
        filename = os.path.basename(path)
        date_from_name = self._parse_filename_date(filename)
        if date_from_name:
            return date_from_name

        # 4. Sibling Image Check (原況照片 Live Photos 支援)
        # 若影片本身沒日期，嘗試讀取同名的 HEIC/JPG 照片日期
        if not is_photo:
            base_path = os.path.splitext(path)[0]
            # 常見的原況照片配對格式
            for img_ext in ['.heic', '.HEIC', '.jpg', '.JPG', '.jpeg', '.JPEG']:
                sibling_path = base_path + img_ext
                # 避免讀取自己 (若副檔名剛好相同，雖然這在 is_photo check 已排除)
                if sibling_path != path and os.path.exists(sibling_path):
                    # 遞迴讀取該照片的日期 (is_photo=True 會觸發 EXIF 讀取)
                    # 為避免無限遞迴，這裡我們只單獨調用 EXIF/JSON 讀取，或者簡單地遞迴但限制深度
                    # 由於 sibling 是 photo，它會走 step 1, 2, 3，不會進 step 4，所以安全。
                    sib_date = self._get_date(sibling_path, is_photo=True)
                    if sib_date:
                        return sib_date

        return None

    def _parse_json_date(self, json_path):
        """解析 Google Takeout JSON"""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 優先讀取 photoTakenTime
                taken = data.get('photoTakenTime', {})
                ts = taken.get('timestamp')
                if ts:
                    return datetime.datetime.fromtimestamp(int(ts))
        except:
            pass
        return None

    def _parse_exif_date(self, dt_str):
        """解析 EXIF 日期字串 (YYYY:MM:DD HH:MM:SS)"""
        try:
            return datetime.datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
        except:
            return None

    def _get_hash(self, path):
        sha = hashlib.md5()
        with open(path, 'rb') as f:
            while chunk := f.read(CONFIG.BLOCK_SIZE):
                sha.update(chunk)
        return sha.hexdigest()

    def _get_unique_path(self, path):
        base, ext = os.path.splitext(path)
        counter = 1
        new_path = f"{base}_{counter}{ext}"
        while os.path.exists(new_path):
            counter += 1
            new_path = f"{base}_{counter}{ext}"
        return new_path

    def _remove_empty_folders(self, path):
        for root, dirs, files in os.walk(path, topdown=False):
            for name in dirs:
                d = os.path.join(root, name)
                try:
                    if not os.listdir(d):
                        os.rmdir(d)
                except:
                    pass

    def _generate_report(self, dst_root):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        report_path = os.path.join(dst_root, f"Sorting_Report_{timestamp}.txt")
        
        content = [
            f"=== 照片整理報告 (Photo Organizer Pro) ===",
            f"時間: {datetime.datetime.now()}",
            f"來源: {self.source_dir.get()}",
            f"----------------------------------------",
            f"總處理成功: {self.stats['processed']}",
            f"重複略過數: {self.stats['skipped']}",
            f"錯誤數量:   {self.stats['errors']}",
            f"----------------------------------------",
            "\n[失敗檔案列表]:"
        ]
        
        if not self.stats['failed_files']:
            content.append("(無錯誤)")
        else:
            content.extend(self.stats['failed_files'])
            
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(content))
            self._log(f"已生成報告: {os.path.basename(report_path)}")
        except Exception as e:
            self._log(f"生成報告失敗: {e}", 'error')

    def _update_stats_label(self):
        txt = f"已處理: {self.stats['processed']} | 重複: {self.stats['skipped']} | 錯誤: {self.stats['errors']}"
        self.root.after(0, lambda: self.lbl_stats.configure(text=txt))

    def _finish_tasks(self):
        self.is_running = False
        self._update_stats_label()
        self.root.after(0, lambda: self.progress.configure(value=100))
        self.root.after(0, lambda: self._update_ui_state(False))

    def _load_config(self):
        if os.path.exists(CONFIG.CONFIG_FILE):
            try:
                with open(CONFIG.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.source_dir.set(data.get('source', ''))
                    self.dest_dir.set(data.get('dest', ''))
            except:
                pass

    def _on_close(self):
        # Save config
        data = {
            'source': self.source_dir.get(),
            'dest': self.dest_dir.get()
        }
        try:
            with open(CONFIG.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except:
            pass
        
        self.stop_event.set()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = PhotoOrganizerApp(root)
    root.mainloop()
