# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
from pathlib import Path
import threading
import os

from src.utils.config import ConfigConstants, AppConfig
from src.utils.logger import Logger
from src.ui.styles import Styles
from src.core.processor import Processor

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.app_config = AppConfig.get_instance()
        self.logger = Logger.get_instance()
        
        self.root.title(f"{ConfigConstants.APP_NAME} v{ConfigConstants.VERSION}")
        self.root.geometry("950x750")
        
        # Variables
        self.source_dir = tk.StringVar(value=self.app_config.source_dir)
        self.dest_dir = tk.StringVar(value=self.app_config.dest_dir)
        self.mode = tk.StringVar(value="copy")
        self.clean_empty = tk.BooleanVar(value=False)
        self.rename_enabled = tk.BooleanVar(value=False)
        self.gps_enabled = tk.BooleanVar(value=False)
        self.resume_enabled = tk.BooleanVar(value=True)
        self.blur_check_enabled = tk.BooleanVar(value=False)
        
        self.skip_existing = tk.BooleanVar(value=self.app_config.skip_existing)
        self.processor = None
        self.is_running = False
        self.is_paused = False
        
        # Connect Logger
        self.logger.set_callback(self._on_log)
        
        # Setup UI
        Styles.setup_styles(self.root)
        self._create_widgets()
        
        # Cleanup
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_widgets(self):
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(container)
        header.pack(fill="x", pady=(0, 15))
        ttk.Label(header, text="✨ " + ConfigConstants.APP_NAME, font=("Microsoft JhengHei UI", 16, "bold"), foreground="#2C3E50").pack(side="left")
        ttk.Label(header, text=f"v{ConfigConstants.VERSION}", font=("Segoe UI", 10), foreground="#7F8C8D").pack(side="left", padx=10, pady=(8,0))

        # Path Section
        self._create_path_section(container)
        # Options
        self._create_options_section(container)
        # Controls
        self._create_control_section(container)
        # Logs
        self._create_log_section(container)

    def _create_path_section(self, parent):
        frame = ttk.LabelFrame(parent, text=" 📂 資料夾路徑設定 ", padding=15)
        frame.pack(fill="x", pady=10)
        
        grid_opts = {'padx': 5, 'pady': 8, 'sticky': 'w'}
        
        ttk.Label(frame, text="來源資料夾:", style="Section.TLabel").grid(row=0, column=0, **grid_opts)
        ttk.Entry(frame, textvariable=self.source_dir, width=65).grid(row=0, column=1, padx=5, pady=8)
        ttk.Button(frame, text="瀏覽...", command=self._select_source).grid(row=0, column=2, padx=5, pady=8)
        
        ttk.Label(frame, text="目標資料夾:", style="Section.TLabel").grid(row=1, column=0, **grid_opts)
        ttk.Entry(frame, textvariable=self.dest_dir, width=65).grid(row=1, column=1, padx=5, pady=8)
        ttk.Button(frame, text="瀏覽...", command=self._select_dest).grid(row=1, column=2, padx=5, pady=8)

    def _create_options_section(self, parent):
        frame = ttk.LabelFrame(parent, text=" ⚙️ 整理規則與選項 ", padding=15)
        frame.pack(fill="x", pady=10)
        
        # 1. Mode Selection (Row 0)
        mode_frame = ttk.Frame(frame)
        mode_frame.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        
        ttk.Label(mode_frame, text="運作模式:", font=("Microsoft JhengHei UI", 10, "bold")).pack(side="left", padx=(5, 15))
        ttk.Radiobutton(mode_frame, text="複製 (Copy) - 保留原始檔案", variable=self.mode, value="copy").pack(side="left", padx=10)
        ttk.Radiobutton(mode_frame, text="移動 (Move) - 原始檔案將被移動", variable=self.mode, value="move", command=self._toggle_clean_option).pack(side="left", padx=10)
        
        # Performance Tip
        tip_text = "💡 效能提示：\n   • 移動 (Move)：同磁碟極快 (僅修改路徑)，跨磁碟較慢 (讀+寫+刪)\n   • 複製 (Copy)：跨實體磁碟最快 (平行讀寫)，同磁碟較慢 (磁頭來回)"
        ttk.Label(frame, text=tip_text, foreground="#7F8C8D", font=("Segoe UI", 9)).grid(row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 10))

        ttk.Separator(frame, orient='horizontal').grid(row=2, column=0, columnspan=3, sticky="ew", pady=5)

        # 2. Functional Options (Grid Layout)
        # Column 0: Organization
        # Column 1: Filtering / Skip
        # Column 2: Advanced / Cleanup
        
        # Row 3 (was Row 2)
        ttk.Checkbutton(frame, text="標準化重命名 (YYYY_MM_DD_流水號)", variable=self.rename_enabled).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        
        self.skip_existing = tk.BooleanVar(value=bool(getattr(self.app_config, 'skip_existing', False)))
        ttk.Checkbutton(frame, text="跳過目標已存在的檔案 (去重)", variable=self.skip_existing).grid(row=3, column=1, sticky="w", padx=10, pady=5)
        
        self.chk_clean = ttk.Checkbutton(frame, text="刪除來源空資料夾 (僅移動模式)", variable=self.clean_empty)
        self.chk_clean.grid(row=3, column=2, sticky="w", padx=10, pady=5)

        # Row 4 (was Row 3)
        ttk.Checkbutton(frame, text="啟用 GPS 地點分類 (國別_城市)", variable=self.gps_enabled).grid(row=4, column=0, sticky="w", padx=10, pady=5)
        ttk.Checkbutton(frame, text="啟用斷點續傳", variable=self.resume_enabled).grid(row=4, column=1, sticky="w", padx=10, pady=5)
        ttk.Checkbutton(frame, text="啟用模糊偵測 (實驗性)", variable=self.blur_check_enabled).grid(row=4, column=2, sticky="w", padx=10, pady=5)

        ttk.Separator(frame, orient='horizontal').grid(row=5, column=0, columnspan=3, sticky="ew", pady=10)
        
        # 3. Simulation / Action (Row 6)
        self.dry_run = tk.BooleanVar(value=False)
        chk_dry = tk.Checkbutton(frame, text="✨ 模擬執行 (預覽模式) - 僅產出報表，不寫入硬碟", 
                       variable=self.dry_run, 
                       font=("Microsoft JhengHei UI", 10, "bold"),
                       bg='#e8f5e9', fg='#2e7d32', selectcolor='#e8f5e9',
                       activebackground='#c8e6c9', activeforeground='#2e7d32',
                       padx=10, pady=5, relief="flat", bd=0)
        chk_dry.grid(row=6, column=0, columnspan=3, sticky="w", padx=5)
        
        # Configure Grid Weights
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

        self._toggle_clean_option()

    def _create_control_section(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=15)
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side="left")
        
        self.btn_start = ttk.Button(btn_frame, text="▶ 開始整理", command=self._start_thread, style="Primary.TButton", width=15)
        self.btn_start.pack(side="left", padx=(0, 10))
        self.btn_pause = ttk.Button(btn_frame, text="⏸ 暫停", command=self._toggle_pause, state="disabled", width=10)
        self.btn_pause.pack(side="left", padx=10)
        self.btn_stop = ttk.Button(btn_frame, text="⏹ 停止", command=self._stop_process, state="disabled", style="Danger.TButton", width=10)
        self.btn_stop.pack(side="left", padx=10)
        
        self.lbl_stats = ttk.Label(frame, text="準備就緒", font=("Microsoft JhengHei UI", 11), foreground="#4A90E2")
        self.lbl_stats.pack(side="right", padx=10, fill="y")

    def _create_log_section(self, parent):
        frame = ttk.LabelFrame(parent, text=" 📊 即時監控儀表板 ", padding=15)
        frame.pack(fill="both", expand=True, pady=(0, 5))
        
        # Dashboard Grid
        dash_frame = ttk.Frame(frame)
        dash_frame.pack(fill="x", pady=(0, 10))
        
        # Helper to create card
        def create_card(parent, title, col):
            f = ttk.Frame(parent, borderwidth=1, relief="solid", padding=10)
            f.grid(row=0, column=col, padx=5, sticky="ew")
            parent.columnconfigure(col, weight=1)
            ttk.Label(f, text=title, font=("Segoe UI", 9), foreground="#7F8C8D").pack()
            val = ttk.Label(f, text="-", font=("Consolas", 14, "bold"), foreground="#2C3E50")
            val.pack()
            return val
            
        self.lbl_speed = create_card(dash_frame, "傳輸速度", 0)
        self.lbl_eta = create_card(dash_frame, "預估剩餘時間", 1)
        self.lbl_size_prog = create_card(dash_frame, "處理容量進度", 2)
        
        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 5))
        
        self.lbl_current_file = ttk.Label(frame, text="等待開始...", font=("Microsoft JhengHei UI", 9), foreground="#7F8C8D")
        self.lbl_current_file.pack(fill="x", pady=(0, 10))
        
        ttk.Label(frame, text="執行日誌:", font=("Microsoft JhengHei UI", 9, "bold")).pack(anchor="w")
        self.log_area = scrolledtext.ScrolledText(frame, state='disabled', height=8, font=("Consolas", 10), bg="#FAFAFA", relief="flat", padx=10, pady=10)
        self.log_area.pack(fill="both", expand=True)
        self.log_area.tag_config('error', foreground='#E74C3C')
        self.log_area.tag_config('warn', foreground='#D35400')

    def _on_progress(self, data):
         self.root.after(0, lambda: self._update_progress_ui(data))

    def _on_status(self, msg):
        self.root.after(0, lambda: self.lbl_stats.configure(text=msg))

    def _update_progress_ui(self, data):
        # data = {current, total, filename, processed_size, total_size, speed, eta}
        current = data['current']
        total = data['total']
        filename = data['filename']
        
        if total > 0:
            val = (current / total) * 100
            self.progress.configure(value=val)
            
        self.lbl_current_file.configure(text=f"正在處理: {filename}")
        self.lbl_stats.configure(text=f"進度: {current}/{total}")
        
        # Update Dashboard
        try:
            speed_mb = data['speed'] / (1024*1024)
            self.lbl_speed.configure(text=f"{speed_mb:.1f} MB/s")
            
            eta = int(data['eta'])
            mins, secs = divmod(eta, 60)
            if mins > 60:
                hrs, mins = divmod(mins, 60)
                self.lbl_eta.configure(text=f"{hrs}h {mins}m")
            else:
                self.lbl_eta.configure(text=f"{mins}m {secs}s")
                
            p_size = self._format_size(data['processed_size'])
            t_size = self._format_size(data['total_size'])
            self.lbl_size_prog.configure(text=f"{p_size} / {t_size}")
            
        except Exception:
            pass

    def _format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"

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

    def _on_log(self, msg, level):
        def _append():
            self.log_area.configure(state='normal')
            if level == 'error':
                self.log_area.insert(tk.END, f"[錯誤] {msg}\n", 'error')
            elif level == 'warn':
                self.log_area.insert(tk.END, f"[跳過] {msg}\n", 'warn')
            else:
                self.log_area.insert(tk.END, f"{msg}\n")
            self.log_area.see(tk.END)
            self.log_area.configure(state='disabled')
        self.root.after(0, _append)

    def _start_thread(self):
        src = self.source_dir.get()
        dst = self.dest_dir.get()
        
        if not src or not os.path.exists(src):
            messagebox.showerror("錯誤", "來源資料夾無效！")
            return
        if not dst or not os.path.exists(dst):
            messagebox.showerror("錯誤", "目標資料夾無效！")
            return
            
        # Update Config
        self.app_config.source_dir = src
        self.app_config.dest_dir = dst
        self.app_config.skip_existing = self.skip_existing.get()
        self.app_config.save()
        
        config_options = {
            'mode': self.mode.get(),
            'clean_empty': self.clean_empty.get(),
            'rename_enabled': self.rename_enabled.get(),
            'gps_enabled': self.gps_enabled.get(),
            'resume_enabled': self.resume_enabled.get(),
            'blur_check_enabled': self.blur_check_enabled.get(),
            'skip_existing': self.skip_existing.get(),
            'dry_run': self.dry_run.get(),
            'src_root': src,
            'dst_root': dst
        }
        
        self.log_area.configure(state='normal')
        self.log_area.delete('1.0', tk.END)
        self.log_area.configure(state='disabled')
        self._update_ui_state(True)
        
        self.processor = Processor(
            config_options, 
            progress_callback=self._on_progress,
            status_callback=self._on_status
        )
        
        threading.Thread(target=self._run_process, daemon=True).start()

    def _run_process(self):
        try:
            results = self.processor.start()
            self._on_log(f"=== 任務完成 ===", "info")
            msg = f"整理完成！\n已處理: {results['processed']}\n跳過: {results['skipped']}\n錯誤: {results['errors']}"
            self.root.after(0, lambda: messagebox.showinfo("完成", msg))
        except Exception as e:
            self._on_log(f"執行中斷: {e}", "error")
        finally:
            self.root.after(0, lambda: self._update_ui_state(False))



    def _toggle_pause(self):
        if not self.processor: return
        self.is_paused = not self.is_paused
        
        if self.is_paused:
            self.processor.pause()
            self.btn_pause.configure(text="▶ 繼續")
            self._on_log(">> 任務已暫停", "warn")
        else:
            self.processor.resume()
            self.btn_pause.configure(text="⏸ 暫停")
            self._on_log(">> 任務繼續", "info")

    def _stop_process(self):
        if not self.processor: return
        if messagebox.askyesno("確認", "確定要停止目前的任務嗎？"):
            self.processor.stop()
            self._on_log(">> 正在停止任務...", "warn")

    def _update_ui_state(self, running):
        state = 'disabled' if running else 'normal'
        inv_state = 'normal' if running else 'disabled'
        self.btn_start.configure(state=state)
        self.btn_pause.configure(state=inv_state)
        self.btn_stop.configure(state=inv_state)

    def _on_close(self):
        if self.processor:
            self.processor.stop()
        self.app_config.save()
        self.root.destroy()
