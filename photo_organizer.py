
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
    # 註冊 HEIC Opener
    pillow_heif.register_heif_opener()
except ImportError:
    Image = None
    print("警告: 未安裝 Pillow 或 pillow-heif，部分圖片功能可能失效。")

# --- GPS Module Import ---
try:
    import reverse_geocoder as rg
except ImportError:
    rg = None
    print("警告: 未安裝 reverse_geocoder，GPS 分類功能將無法使用。")

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
        self.gps_enabled = tk.BooleanVar(value=False)    # GPS 分類 (Beta)

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
        style.theme_use('clam') # 使用 clam 作為基底，更容易自定義顏色
        
        # --- 色票 (Color Palette) ---
        BG_COLOR = "#F4F6F9"       # 淺灰藍背景 (Modern Light)
        SECTION_BG = "#FFFFFF"     #區塊白底
        PRIMARY_COLOR = "#4A90E2"  # 主色 (柔和藍)
        TEXT_COLOR = "#2C3E50"     # 深灰文字
        SUCCESS_COLOR = "#2ECC71"  # 成功綠
        WARN_COLOR = "#F1C40F"     # 警告黃
        ERROR_COLOR = "#E74C3C"    # 錯誤紅

        # --- 字型 (Fonts) ---
        MAIN_FONT = ("Microsoft JhengHei UI", 10)
        BOLD_FONT = ("Microsoft JhengHei UI", 10, "bold")
        HEADER_FONT = ("Microsoft JhengHei UI", 11, "bold")
        TITLE_FONT = ("Microsoft JhengHei UI", 12, "bold")

        self.root.configure(bg=BG_COLOR)

        # 基礎 Frame / Label
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=MAIN_FONT)
        style.configure("Section.TFrame", background=SECTION_BG)
        style.configure("Section.TLabel", background=SECTION_BG, foreground=TEXT_COLOR, font=MAIN_FONT)

        # LabelFrame 樣式
        style.configure("TLabelframe", background=SECTION_BG, bordercolor="#DCE1E7", borderwidth=1)
        style.configure("TLabelframe.Label", background=SECTION_BG, foreground=PRIMARY_COLOR, font=HEADER_FONT)

        # 按鈕樣式 (Flat Design)
        style.configure("TButton", 
            font=BOLD_FONT, 
            borderwidth=0, 
            focuscolor="none", 
            padding=8,
            background="#E0E6ED",
            foreground=TEXT_COLOR
        )
        style.map("TButton",
            background=[('active', PRIMARY_COLOR), ('disabled', '#D0D0D0')],
            foreground=[('active', 'white'), ('disabled', '#888888')]
        )

        # 特殊按鈕樣式
        style.configure("Primary.TButton", background=PRIMARY_COLOR, foreground="white")
        style.map("Primary.TButton", background=[('active', '#357ABD')]) # Darker Blue

        style.configure("Danger.TButton", background=ERROR_COLOR, foreground="white")
        style.map("Danger.TButton", background=[('active', '#C0392B')])

        # Entry / Checkbox / Radio
        style.configure("TEntry", padding=5, bordercolor=PRIMARY_COLOR)
        style.configure("TCheckbutton", background=SECTION_BG, font=MAIN_FONT, focuscolor="none")
        style.configure("TRadiobutton", background=SECTION_BG, font=MAIN_FONT, focuscolor="none")
        
        # Progressbar
        style.configure("Horizontal.TProgressbar", troughcolor="#E0E0E0", background=PRIMARY_COLOR, bordercolor=BG_COLOR, lightcolor=PRIMARY_COLOR, darkcolor=PRIMARY_COLOR)

    def _create_widgets(self):
        # 主容器：加上 padding 讓畫面不要貼邊
        main_container = ttk.Frame(self.root, padding=20)
        main_container.pack(fill="both", expand=True)

        # 標題區
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill="x", pady=(0, 15))
        ttk.Label(header_frame, text="✨ " + CONFIG.APP_NAME, font=("Microsoft JhengHei UI", 16, "bold"), foreground="#2C3E50").pack(side="left")
        ttk.Label(header_frame, text=f"v{CONFIG.VERSION}", font=("Segoe UI", 10), foreground="#7F8C8D").pack(side="left", padx=10, pady=(8,0))

        # 1. 檔案路徑設定區
        self._create_path_section(main_container)
        
        # 2. 選項設定區
        self._create_options_section(main_container)
        
        # 3. 控制按鈕區
        self._create_control_section(main_container)
        
        # 4. 訊息與日誌區
        self._create_log_section(main_container)

    def _create_path_section(self, parent):
        # 使用自定義 Section 背景
        frame = ttk.LabelFrame(parent, text=" 📂 資料夾路徑設定 ", padding=15)
        frame.pack(fill="x", pady=10)
        
        grid_opts = {'padx': 5, 'pady': 8, 'sticky': 'w'}
        
        # Source
        ttk.Label(frame, text="來源資料夾:", style="Section.TLabel").grid(row=0, column=0, **grid_opts)
        src_entry = ttk.Entry(frame, textvariable=self.source_dir, width=65)
        src_entry.grid(row=0, column=1, padx=5, pady=8)
        ttk.Button(frame, text="瀏覽...", command=self._select_source).grid(row=0, column=2, padx=5, pady=8)
        
        # Destination
        ttk.Label(frame, text="目標資料夾:", style="Section.TLabel").grid(row=1, column=0, **grid_opts)
        dst_entry = ttk.Entry(frame, textvariable=self.dest_dir, width=65)
        dst_entry.grid(row=1, column=1, padx=5, pady=8)
        ttk.Button(frame, text="瀏覽...", command=self._select_dest).grid(row=1, column=2, padx=5, pady=8)

    def _create_options_section(self, parent):
        frame = ttk.LabelFrame(parent, text=" ⚙️ 整理規則與選項 ", padding=15)
        frame.pack(fill="x", pady=10)
        
        # 使用 Grid 佈局讓選項排列更整齊
        # Row 0: 模式選擇
        mode_frame = ttk.Frame(frame, style="Section.TFrame")
        mode_frame.pack(fill="x", anchor="w", pady=5)
        
        ttk.Label(mode_frame, text="運作模式:", style="Section.TLabel", font=("Microsoft JhengHei UI", 10, "bold")).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(mode_frame, text="複製 (Copy) - 保留原檔，最安全", variable=self.mode, value="copy").pack(side="left", padx=10)
        ttk.Radiobutton(mode_frame, text="移動 (Move) - 整理後移動，節省空間", variable=self.mode, value="move", command=self._toggle_clean_option).pack(side="left", padx=10)

        # Separator
        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)

        # Row 1: 進階選項
        opts_frame = ttk.Frame(frame, style="Section.TFrame")
        opts_frame.pack(fill="x", anchor="w", pady=5)
        
        self.chk_clean = ttk.Checkbutton(opts_frame, text="刪除來源空資料夾 (僅移動模式)", variable=self.clean_empty)
        self.chk_clean.pack(side="left", padx=(0, 20))
        
        self.chk_rename = ttk.Checkbutton(opts_frame, text="標準化重命名 (YYYY_MM_DD_流水號)", variable=self.rename_enabled)
        self.chk_rename.pack(side="left", padx=20)

        # GPS Checkbox
        self.chk_gps = ttk.Checkbutton(opts_frame, text="啟用 GPS 地點分類 (國別_城市)", variable=self.gps_enabled)
        self.chk_gps.pack(side="left", padx=20)
        if rg is None:
            self.chk_gps.configure(state='disabled', text="啟用 GPS (未安裝 reverse_geocoder)")
        
        # 提示文字
        ttk.Label(opts_frame, text="* 原況照片(Live Photos)將強制保留原名以維持配對", font=("Microsoft JhengHei UI", 9), foreground="#7F8C8D", style="Section.TLabel").pack(side="left", padx=20)
        
        self._toggle_clean_option() # 初始化狀態

    def _create_control_section(self, parent):
        frame = ttk.Frame(parent) # 透明背景
        frame.pack(fill="x", pady=15)
        
        # 左側按鈕群
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side="left")
        
        self.btn_start = ttk.Button(btn_frame, text="▶ 開始整理", command=self._start_thread, style="Primary.TButton", width=15)
        self.btn_start.pack(side="left", padx=(0, 10))
        
        self.btn_pause = ttk.Button(btn_frame, text="⏸ 暫停", command=self._toggle_pause, state="disabled", width=10)
        self.btn_pause.pack(side="left", padx=10)
        
        self.btn_stop = ttk.Button(btn_frame, text="⏹ 停止", command=self._stop_process, state="disabled", style="Danger.TButton", width=10)
        self.btn_stop.pack(side="left", padx=10)
        
        # 右側狀態
        status_frame = ttk.Frame(frame, padding=5, relief="solid", borderwidth=1)
        # 這裡不設定邊框顏色，用預設的
        # 為了美觀，這邊簡單用 Label 代替
        self.lbl_stats = ttk.Label(frame, text="準備就緒", font=("Microsoft JhengHei UI", 11), foreground="#4A90E2")
        self.lbl_stats.pack(side="right", padx=10, fill="y")

    def _create_log_section(self, parent):
        frame = ttk.LabelFrame(parent, text=" 📝 執行進度與日誌 ", padding=15)
        frame.pack(fill="both", expand=True, pady=(0, 5))
        
        # 進度條
        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 10))
        
        # Log 區域 (含 Scrollbar)
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True)

        self.log_area = scrolledtext.ScrolledText(
            log_frame, 
            state='disabled', 
            height=8, 
            font=("Consolas", 10),
            bg="white",
            fg="#2C3E50",
            relief="flat",
            padx=10,
            pady=10
        )
        self.log_area.pack(fill="both", expand=True)
        
        # 加一點邊框給 log area
        # 由於 ScrolledText 本身不好改 border color，外包一個 frame 模擬


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

        # GPS Library Check
        if self.gps_enabled.get() and rg is None:
            messagebox.showwarning("警告", "尚未安裝 reverse_geocoder，將自動略過 GPS 分類功能。")
            self.gps_enabled.set(False)
        
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
            
            # --- GPS 子資料夾處理 (Option A) ---
            if self.gps_enabled.get():
                location_subfolder = self._get_location_folder(file_path, is_photo)
                if location_subfolder:
                    target_dir = os.path.join(target_dir, location_subfolder)
            
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

    # --- GPS & Helper Functions ---

    def _get_location_folder(self, path, is_photo):
        """嘗試從圖片提取 GPS 並反查 Country_City"""
        if not is_photo or not Image or not rg:
            return None
        
        lat_lon = self._get_lat_lon(path)
        if not lat_lon:
            return None
            
        try:
            # reverse_geocoder 接受 [(lat, lon)]
            # 首次載入會需要下載資料 (約 30MB 記憶體)
            results = rg.search([lat_lon], mode=2) 
            if results:
                data = results[0]
                country = data.get('cc', 'Unknown')
                city = data.get('name', 'Unknown')
                
                # 清理檔案名稱非法字元
                safe_country = "".join([c for c in country if c.isalnum() or c in (' ', '_')]).strip()
                safe_city = "".join([c for c in city if c.isalnum() or c in (' ', '_')]).strip()
                
                if not safe_country: safe_country = "Unknown"
                if not safe_city: safe_city = "Location"
                
                return f"{safe_country}_{safe_city}"
        except Exception:
            pass
            
        return None

    def _get_lat_lon(self, path):
        """從 EXIF 提取經緯度 (Decimal)"""
        try:
            img = Image.open(path)
            exif = img.getexif()
            if not exif:
                return None
                
            # GPS Info Tag ID = 34853
            gps_info = exif.get_ifd(34853)
            if not gps_info:
                return None
            
            gps_lat_ref = gps_info.get(1)
            gps_lat = gps_info.get(2)
            gps_lon_ref = gps_info.get(3)
            gps_lon = gps_info.get(4)
            
            if gps_lat and gps_lat_ref and gps_lon and gps_lon_ref:
                lat = self._convert_to_degrees(gps_lat)
                lon = self._convert_to_degrees(gps_lon)
                
                if gps_lat_ref != "N": lat = -lat
                if gps_lon_ref != "E": lon = -lon
                return (lat, lon)
                
        except Exception:
            pass
        return None

    def _convert_to_degrees(self, value):
        """Helper to convert DMS tuple to decimal degrees"""
        try:
            d = value[0]
            m = value[1]
            s = value[2]
            return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)
        except:
            return 0.0

if __name__ == "__main__":
    root = tk.Tk()
    app = PhotoOrganizerApp(root)
    root.mainloop()
