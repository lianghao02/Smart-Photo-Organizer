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
import ctypes
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
import webview

# --- 選用套件 (降級處理) ---
try:
    from PIL import Image, ImageDraw  # type: ignore
except ImportError:
    Image = None
    ImageDraw = None

try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except ImportError:
    pass

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


def is_onedrive_cloud_only(path: str) -> bool:
    """判斷檔案是否為 Windows 上 OneDrive 僅限線上（未下載）的預留檔案"""
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        # 0x1000 = FILE_ATTRIBUTE_OFFLINE
        # 0x00400000 = FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
        # 0x00040000 = FILE_ATTRIBUTE_RECALL_ON_OPEN
        if attrs & (0x1000 | 0x00400000 | 0x00040000):
            return True
        return False
    except Exception:
        return False


def is_screenshot_by_exif_and_ratio(path: str, strict_mode: bool = True) -> bool:
    """透過檢查無相機物理 EXIF 參數以及長寬比符合手機比例 (>= 1.9) 來智慧辨識螢幕截圖"""
    if Image is None:
        return False
    try:
        filename = os.path.basename(path).lower()
        ext = os.path.splitext(filename)[1]
        
        if filename.startswith(('img', 'dsc', 'c360', 'mvimg')) and ext in {'.jpg', '.jpeg', '.heic', '.heif'}:
            return False
            
        with Image.open(path) as img:
            w, h = img.size
            if w == 0 or h == 0:
                return False
            
            if strict_mode:
                # 手機直向螢幕截圖的高寬比特徵：必須高大於寬，且比例 >= 1.6
                if h <= w or (h / w) < 1.6:
                    return False
                    
                # 2. 寬度尺寸限制排除 (手機實體螢幕直向寬度上限一般為 1440 像素)
                if w > 1440:
                    return False
                
            exif = img.getexif()
            if not exif:
                # 完全沒有 EXIF 且符合手機瘦長長寬比，高機率是螢幕截圖
                return True
                
            # 常見相機感光元件物理參數 Tag ID
            camera_tags = {37378, 33437, 37377, 33434, 34855}
            
            # 檢查標準 EXIF 屬性
            for tag in camera_tags:
                if tag in exif:
                    return False
                    
            # 檢查 SubIFD (34665) 屬性
            if 34665 in exif:
                try:
                    sub = exif.get_ifd(34665)
                    for tag in camera_tags:
                        if tag in sub:
                            return False
                except Exception:
                    pass
            return True
    except Exception:
        return False


import subprocess

def parse_shell_date(raw_dt_str: str) -> Optional[datetime.datetime]:
    """穩健地解析 Windows Shell 返回的拍攝日期字串 (排除隱藏的 unicode 標記)"""
    if not raw_dt_str:
        return None
    # 移除非數字/非斜線/橫槓/冒號/空白的控制字元
    # Windows Shell 常在日期字串中加入 Left-to-Right \u200e 標記
    dt_str = "".join(c for c in raw_dt_str if c.isdigit() or c in '/:- ')
    
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', dt_str)
    if m:
        try:
            h = m_min = 0
            m_time = re.search(r'(\d{1,2}):(\d{2})', dt_str)
            if m_time:
                h = int(m_time.group(1))
                m_min = int(m_time.group(2))
                # 處理上午/下午
                if '下午' in raw_dt_str or 'pm' in raw_dt_str.lower() or 'PM' in raw_dt_str:
                    if h < 12: h += 12
                elif '上午' in raw_dt_str or 'am' in raw_dt_str.lower() or 'AM' in raw_dt_str:
                    if h == 12: h = 0
            return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), h, m_min)
        except Exception:
            pass
    return None


import base64

class WinShellReader:
    """透過 Windows Shell COM 與持久背景 PowerShell 管道，在不下載相片的前提下讀取雲端後設資料，並高速管理 Windows 捷徑"""
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        
    def start(self):
        if os.name != 'nt':
            return
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            # 使用 utf-8 讀寫 ASCII-safe Base64 管道
            self.proc = subprocess.Popen(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', '-'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                startupinfo=startupinfo
            )
            
            # 定義 PowerShell helper 函數
            init_script = """
            function Get-ShellDetailsB64 {
                param([string]$b64Path)
                try {
                    $bytes = [System.Convert]::FromBase64String($b64Path)
                    $filePath = [System.Text.Encoding]::UTF8.GetString($bytes)
                    
                    $absPath = [System.IO.Path]::GetFullPath($filePath)
                    $dir = [System.IO.Path]::GetDirectoryName($absPath)
                    $name = [System.IO.Path]::GetFileName($absPath)
                    
                    $shell = New-Object -ComObject Shell.Application
                    $folder = $shell.NameSpace($dir)
                    $item = $folder.ParseName($name)
                    
                    if ($item) {
                        # 12: 拍攝日期, 30: 相機型號, 32: 製造商, 176: 寬度, 178: 高度
                        $dateTaken = $folder.GetDetailsOf($item, 12)
                        $model = $folder.GetDetailsOf($item, 30)
                        $maker = $folder.GetDetailsOf($item, 32)
                        $width = $folder.GetDetailsOf($item, 176)
                        $height = $folder.GetDetailsOf($item, 178)
                        
                        $obj = @{
                            success = $true
                            date_taken = $dateTaken
                            model = $model
                            maker = $maker
                            width = $width
                            height = $height
                        }
                        $json = (ConvertTo-Json $obj -Compress)
                        $jsonBytes = [System.Text.Encoding]::UTF8.GetBytes($json)
                        return [System.Convert]::ToBase64String($jsonBytes)
                    }
                } catch {
                    # 忽略錯誤
                }
                return "eyJzdWNjZXNzIjpmYWxzZX0="
            }

            function New-LinkB64 {
                param([string]$b64LinkPath, [string]$b64TargetPath)
                try {
                    $bytesL = [System.Convert]::FromBase64String($b64LinkPath)
                    $linkPath = [System.Text.Encoding]::UTF8.GetString($bytesL)
                    
                    $bytesT = [System.Convert]::FromBase64String($b64TargetPath)
                    $targetPath = [System.Text.Encoding]::UTF8.GetString($bytesT)
                    
                    $parentDir = [System.IO.Path]::GetDirectoryName($linkPath)
                    if (-not (Test-Path $parentDir)) {
                        [System.IO.Directory]::CreateDirectory($parentDir) | Out-Null
                    }
                    
                    $WshShell = New-Object -ComObject WScript.Shell
                    $Shortcut = $WshShell.CreateShortcut($linkPath)
                    $Shortcut.TargetPath = $targetPath
                    $Shortcut.Save()
                    return "eyJzdWNjZXNzIjp0cnVlfQ=="
                } catch {
                    # 忽略
                }
                return "eyJzdWNjZXNzIjpmYWxzZX0="
            }

            function Resolve-LinkB64 {
                param([string]$b64LinkPath)
                try {
                    $bytesL = [System.Convert]::FromBase64String($b64LinkPath)
                    $linkPath = [System.Text.Encoding]::UTF8.GetString($bytesL)
                    
                    if (Test-Path $linkPath) {
                        $WshShell = New-Object -ComObject WScript.Shell
                        $Shortcut = $WshShell.CreateShortcut($linkPath)
                        $targetPath = $Shortcut.TargetPath
                        
                        $obj = @{
                            success = $true
                            target_path = $targetPath
                        }
                        $json = (ConvertTo-Json $obj -Compress)
                        $jsonBytes = [System.Text.Encoding]::UTF8.GetBytes($json)
                        return [System.Convert]::ToBase64String($jsonBytes)
                    }
                } catch {
                    # 忽略
                }
                return "eyJzdWNjZXNzIjpmYWxzZX0="
            }
            """
            self.proc.stdin.write(init_script + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            Logger.get_instance().error(f"無法啟動 WinShellReader: {e}")
            self.proc = None

    def get_properties(self, file_path: str) -> dict:
        if os.name != 'nt':
            return {"success": False}
        if not self.proc or self.proc.poll() is not None:
            try: self.start()
            except: return {"success": False}
        if not self.proc:
            return {"success": False}

        with self.lock:
            try:
                b64_path = base64.b64encode(file_path.encode('utf-8')).decode('ascii')
                cmd = f"Get-ShellDetailsB64 '{b64_path}'"
                self.proc.stdin.write(cmd + "\n")
                self.proc.stdin.flush()
                
                line = self.proc.stdout.readline().strip()
                if line:
                    decoded = base64.b64decode(line.encode('ascii')).decode('utf-8')
                    return json.loads(decoded)
            except Exception:
                pass
        return {"success": False}

    def create_shortcut(self, link_path: str, target_path: str) -> bool:
        """在指定路徑建立指向 target_path 的 Windows 捷徑 (.lnk)"""
        if os.name != 'nt':
            return False
        if not self.proc or self.proc.poll() is not None:
            try: self.start()
            except: return False
        if not self.proc:
            return False

        with self.lock:
            try:
                b64_link = base64.b64encode(link_path.encode('utf-8')).decode('ascii')
                b64_target = base64.b64encode(target_path.encode('utf-8')).decode('ascii')
                cmd = f"New-LinkB64 '{b64_link}' '{b64_target}'"
                self.proc.stdin.write(cmd + "\n")
                self.proc.stdin.flush()
                
                line = self.proc.stdout.readline().strip()
                if line:
                    decoded = base64.b64decode(line.encode('ascii')).decode('utf-8')
                    return json.loads(decoded).get('success', False)
            except Exception:
                pass
        return False

    def resolve_shortcut(self, link_path: str) -> Optional[str]:
        """解析捷徑 (.lnk)，回傳其所指向的實體目標路徑"""
        if os.name != 'nt':
            return None
        if not self.proc or self.proc.poll() is not None:
            try: self.start()
            except: return None
        if not self.proc:
            return None

        with self.lock:
            try:
                b64_link = base64.b64encode(link_path.encode('utf-8')).decode('ascii')
                cmd = f"Resolve-LinkB64 '{b64_link}'"
                self.proc.stdin.write(cmd + "\n")
                self.proc.stdin.flush()
                
                line = self.proc.stdout.readline().strip()
                if line:
                    decoded = base64.b64decode(line.encode('ascii')).decode('utf-8')
                    res = json.loads(decoded)
                    if res.get('success'):
                        return res.get('target_path')
            except Exception:
                pass
        return None

    def stop(self):
        if self.proc:
            try:
                self.proc.stdin.write("exit\n")
                self.proc.stdin.flush()
                self.proc.terminate()
            except:
                pass
            self.proc = None


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
    VERSION     = "2.9"
    CONFIG_FILE = "config.json"
    HISTORY_FILE = "history_log.json"
    BLOCK_SIZE  = 65536

    EXT_PHOTOS: Set[str] = {'.jpg', '.jpeg', '.png', '.heic', '.bmp', '.tiff', '.raw', '.arw', '.webp', '.nef', '.cr2', '.cr3', '.dng', '.orf', '.rw2', '.pef', '.sr2'}
    EXT_VIDEOS: Set[str] = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v'}
    EXT_JUNK:   Set[str] = {'.json', '.ini', '.db', '.html', '.txt', '.tmp', '.url'}
    SCREENSHOT_KEYWORDS  = ['screenshot', 'screen shot', 'captura', '螢幕擷取', '截圖', 'snapshot']


class AppConfig:
    """使用者偏好設定，以 JSON 持久化"""
    _instance: Optional['AppConfig'] = None

    def __init__(self):
        self.source_dir     = ""
        self.dest_dir       = ""
        self.skip_existing  = False
        self.folder_pattern = "ym"
        self.rename_mode    = "date_seq"
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
                    self.source_dir     = data.get('source', '')
                    self.dest_dir       = data.get('dest', '')
                    self.skip_existing  = data.get('skip_existing', False)
                    self.folder_pattern = data.get('folder_pattern', 'ym')
                    self.rename_mode    = data.get('rename_mode', 'date_seq')
            except Exception:
                pass

    def save(self):
        try:
            with open(ConfigConstants.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'source': self.source_dir,
                    'dest': self.dest_dir,
                    'skip_existing': self.skip_existing,
                    'folder_pattern': self.folder_pattern,
                    'rename_mode': self.rename_mode
                }, f, indent=4)
        except Exception as e:
            print(f"⚠️ 無法儲存設定: {e}")


# ==============================================================================
# 模組三：FSUtils — 檔案系統工具
# ==============================================================================
class FSUtils:

    @staticmethod
    def get_unique_path(path: str, reserved_paths: Optional[set] = None) -> str:
        """回傳不重複的路徑（若已存在或已預留則智慧歸併 _N，避免無限產生 _1_1_1）"""
        def is_taken(p: str) -> bool:
            if os.path.exists(p): return True
            if reserved_paths is not None and p in reserved_paths: return True
            return False

        if not is_taken(path):
            return path

        dir_name, file_name = os.path.split(path)
        base, ext = os.path.splitext(file_name)

        # 智慧剝離末尾重複的 _1_1 尾綴，恢復乾淨檔名底色
        clean_base = re.sub(r'(?:_\d+)+$', '', base)
        if not clean_base:
            clean_base = base

        counter = 1
        while True:
            candidate_name = f"{clean_base}_{counter}{ext}"
            candidate_path = os.path.join(dir_name, candidate_name)
            if not is_taken(candidate_path):
                return candidate_path
            counter += 1

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
    def find_empty_folders(path: str, exclude_dirs: Optional[set] = None) -> list[str]:
        """遞迴尋找空資料夾，回傳空資料夾的路徑清單"""
        empty_dirs = []
        if not os.path.exists(path):
            return empty_dirs
        exc = {os.path.abspath(d) for d in exclude_dirs} if exclude_dirs else set()
        for root, dirs, files in os.walk(path, topdown=False):
            abs_root = os.path.abspath(root)
            if any(abs_root.startswith(ex) for ex in exc):
                continue
            for name in dirs:
                d = os.path.join(root, name)
                abs_d = os.path.abspath(d)
                if any(abs_d.startswith(ex) for ex in exc):
                    continue
                try:
                    content = os.listdir(d)
                    if len(content) == 0:
                        empty_dirs.append(d)
                except Exception:
                    pass
        return empty_dirs

    @staticmethod
    def get_sequence_name(target_dir: str, prefix: str, ext: str, dir_counters: dict, mode: str = "date_seq", reserved_paths: Optional[set] = None) -> str:
        """根據重命名模式產生 2024_05_20_001.ext (date_seq) 或 001.ext (pure_seq) 檔名"""
        if mode == "date_seq" and prefix:
            key = (target_dir, prefix)
            file_prefix = f"{prefix}_"
        else:
            key = (target_dir, "pure_sequence")
            file_prefix = ""

        if key not in dir_counters:
            max_seq = 0
            if os.path.exists(target_dir):
                try:
                    if file_prefix:
                        pattern = re.compile(rf'^{re.escape(file_prefix)}(\d+)$', re.IGNORECASE)
                    else:
                        pattern = re.compile(r'^(\d+)$')
                    
                    for fname in os.listdir(target_dir):
                        if fname.lower().endswith(ext.lower()):
                            stem = os.path.splitext(fname)[0]
                            match = pattern.fullmatch(stem)
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

        dir_counters[key] += 1
        seq_num = dir_counters[key]
        safe_reserved = reserved_paths if reserved_paths is not None else set()
        while True:
            new_name = f"{file_prefix}{seq_num:03d}{ext}"
            new_path = os.path.join(target_dir, new_name)
            is_reserved = False
            for p in safe_reserved:
                if str(new_path) == str(p):
                    is_reserved = True
                    break
            is_taken = os.path.exists(new_path) or is_reserved
            if not is_taken:
                return new_path
            seq_num += 1
            dir_counters[key] = seq_num


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

    def get_date(self, path: str, is_photo: bool, is_cloud: bool = False, shell_reader: Any = None) -> Optional[datetime.datetime]:
        # 1. JSON Sidecar
        try:
            for jp in [path + ".json", os.path.splitext(path)[0] + ".json"]:
                if os.path.exists(jp):
                    d = self._parse_json_date(jp)
                    if d and self._is_valid(d, f"JSON:{os.path.basename(jp)}"): return d
        except Exception:
            pass

        # 2. EXIF (照片) - 僅在本機檔案且非雲端時執行，防止觸發 OneDrive 下載
        if is_photo and Image and not is_cloud:
            d = self._get_exif_date(path)
            if d: return d

        # 2.5 雲端 Shell 屬性拍攝日期 - 僅在雲端且有 shell_reader 時執行，防止下載
        if is_cloud and shell_reader:
            props = shell_reader.get_properties(path)
            if props.get('success') and props.get('date_taken'):
                d = parse_shell_date(props.get('date_taken'))
                if d and self._is_valid(d, "Shell-DateTaken"): return d

        # 3. 檔名 Regex
        d = self._parse_filename_date(os.path.basename(path))
        if d and self._is_valid(d, "Filename"): return d

        # 4. 找同名照片（影片/Live Photo 配對）
        if not is_photo:
            base = os.path.splitext(path)[0]
            for img_ext in ['.heic', '.HEIC', '.jpg', '.JPG', '.jpeg', '.JPEG']:
                sibling = base + img_ext
                if sibling != path and os.path.exists(sibling):
                    d = self.get_date(sibling, is_photo=True, is_cloud=is_cloud, shell_reader=shell_reader)
                    if d is not None: return d
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
    _cache_lock = threading.Lock()
    _api_lock = threading.Lock()
    _last_req_time = 0.0

    @staticmethod
    def _init_geo():
        if ImageOps._geolocator is None and _HAS_GEOPY and Nominatim is not None:
            ImageOps._geolocator = Nominatim(user_agent="smart_photo_organizer_v2", timeout=3)

    @staticmethod
    def is_blurry(path: str, threshold: float = 100.0) -> tuple[bool, float]:
        """回傳 (is_blurry, score)，使用 Laplacian Variance，先縮圖提昇效能"""
        if not _HAS_CV2 or cv2 is None:  # type: ignore
            return False, 0.0
        try:
            arr = np.fromfile(path, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)  # type: ignore
            if img is None: return False, 0.0
            
            # 自動縮小影像至 1024px，避免超大解析度影響 Laplacian 計算速度與佔用記憶體
            h, w = img.shape[:2]
            max_dim = 1024
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)  # type: ignore
                
            score = cv2.Laplacian(img, cv2.CV_64F).var()  # type: ignore
            return score < threshold, score
        except Exception:
            return False, 0.0

    @staticmethod
    def get_location_folder(path: str) -> Optional[str]:
        """回傳 '國家_城市' 字串，優先線上繁中，次用離線 reverse_geocoder，具備全域限速與執行緒安全鎖"""
        if not Image: return None
        lat_lon = ImageOps._get_lat_lon(path)
        if not lat_lon: return None
        lat, lon = lat_lon

        if _HAS_GEOPY:
            ImageOps._init_geo()
            if ImageOps._geolocator is not None:
                cache_key = (float(f"{float(lat):.3f}") if lat is not None else 0.0, 
                             float(f"{float(lon):.3f}") if lon is not None else 0.0)
                
                # 快取安全讀取
                with ImageOps._cache_lock:
                    if cache_key in ImageOps._geo_cache:
                        return ImageOps._geo_cache[cache_key]
                
                # API 限速保護與安全呼叫
                loc = None
                try:
                    with ImageOps._api_lock:
                        elapsed = time.time() - ImageOps._last_req_time
                        if elapsed < 1.0:
                            time.sleep(1.0 - elapsed)
                        loc = ImageOps._geolocator.reverse((lat, lon), language='zh-TW', exactly_one=True)  # type: ignore
                        ImageOps._last_req_time = time.time()
                except (GeocoderTimedOut, GeocoderServiceError, Exception):
                    # 即使出錯，亦需釋放鎖並更新時間以防密集錯誤請求
                    pass
                
                if loc:
                    addr = loc.raw.get('address', {})
                    country = addr.get('country', '未知國家')
                    city = addr.get('city', addr.get('county', addr.get('town', addr.get('suburb', '未知城市'))))
                    result = f"{country}_{city}"
                    # 快取安全寫入
                    with ImageOps._cache_lock:
                        ImageOps._geo_cache[cache_key] = result
                    return result

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
      dry_run / src_root / dst_root / onedrive_protect / smart_screenshot
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
        
        # 自動偵測 OneDrive 路徑以強制開啟保護
        self.onedrive_protect = self.config.get('onedrive_protect', False)
        src_root = self.config.get('src_root', '')
        if src_root and "onedrive" in src_root.lower():
            self.onedrive_protect = True
            self.logger.info("🛡️ 偵測到 OneDrive 路徑，自動啟動『雲端下載防禦機制』")
        self.shell_reader = WinShellReader() if os.name == 'nt' else None

    def stop(self):  self.stop_event.set(); self.pause_event.set()
    def pause(self): self.pause_event.clear()
    def resume(self): self.pause_event.set()

    def start(self):
        if self.shell_reader:
            self.shell_reader.start()
        try:
            self._load_history()
            src_root = self.config['src_root']
            dst_root = self.config.get('dst_root', '')
            mode_str = "原地清理 (Cleanup)" if self.config['mode'] == 'cleanup' else self.config['mode'].upper()
            if self.config.get('dry_run'): mode_str += " (預覽模式)"
            self.logger.info(f"🚀 開始任務\n來源: {src_root}" + (f"\n目標: {dst_root}" if self.config['mode'] != 'cleanup' else "") + f"\n模式: {mode_str}")

            if self.config['mode'] != 'cleanup' and self.config.get('skip_existing'):
                if self.status_callback: self.status_callback("正在建立目標索引 (去重用)...")
                self._index_destination(dst_root)
                self.logger.info(f"目標索引完成: {sum(len(v) for v in self.dst_index.values())} 檔")

            if self.status_callback: self.status_callback("正在掃描檔案...")
            all_files, total_size = self._scan_files(src_root)
            self.source_files_set = set(os.path.abspath(f) for f in all_files)
            total_count = len(all_files)
            with self.stats_lock: self.stats['total_size'] = total_size

            if total_count == 0:
                self.logger.warn("⚠️ 找不到任何檔案。")
                return self.stats

            if self.config.get('rename_enabled') and self.config['mode'] != 'cleanup':
                if self.status_callback: self.status_callback("正在讀取拍攝時間進行排序 (作法 A)...")
                self.logger.info("啟動強迫序號模式，正在進行第一階段時間掃描...")
                file_dates = []
                for i, f in enumerate(all_files):
                    if self.stop_event.is_set(): break
                    ext = str(os.path.splitext(f)[1]).lower()
                    is_photo = ext in ConfigConstants.EXT_PHOTOS
                    is_cloud = False
                    if self.onedrive_protect:
                        is_cloud = is_onedrive_cloud_only(f)
                    date_obj = self.date_parser.get_date(f, is_photo, is_cloud, self.shell_reader)
                    if not date_obj:
                        try:
                            ctime = os.path.getctime(f)
                            date_obj = datetime.datetime.fromtimestamp(ctime)
                        except Exception:
                            date_obj = datetime.datetime.min
                    file_dates.append((f, date_obj))
                    if i % 100 == 0 and self.status_callback:
                        self.status_callback(f"正在讀取拍攝時間... ({i}/{total_count})")
                
                # 依時間排序
                file_dates.sort(key=lambda x: x[1])
                all_files = [x[0] for x in file_dates]
                
                # 強制使用單執行緒確保序號產生的順序正確
                max_workers = 1
                self.logger.info("排序完成，開始依序處理並產生強迫序號...")
            else:
                self.logger.info(f"共發現 {total_count} 個檔案 ({self._fmt(total_size)})，開始並行處理...")
                max_workers = min(32, (os.cpu_count() or 1) + 4)
                
            start_time  = time.time()

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 若為單執行緒(強迫序號)，需維持原陣列順序提交
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

            if not self.stop_event.is_set():
                if self.config['mode'] == 'cleanup':
                    if self.status_callback: self.status_callback("正在鏡像空資料夾捷徑...")
                    self._mirror_empty_folders(src_root)
                elif self.config['mode'] == 'move' and self.config['clean_empty']:
                    if not self.config.get('dry_run'):
                        self.logger.info("正在清理空資料夾...")
                        FSUtils.remove_empty_folders(src_root)

            if self.config.get('dry_run'): self._export_preview_report()
            return self.stats
        except Exception as e:
            self.logger.error(f"❌ 嚴重錯誤: {e}")
            raise
        finally:
            if self.shell_reader:
                self.shell_reader.stop()

    def _mirror_empty_folders(self, src_root):
        to_clean_dir = os.path.join(src_root, "_ToClean")
        if self.config.get('dry_run'):
            # 預覽模式
            empty_dirs = FSUtils.find_empty_folders(src_root, exclude_dirs={to_clean_dir})
            for d in empty_dirs:
                rel = os.path.relpath(d, src_root).replace(os.sep, "_")
                lnk_path = os.path.join(to_clean_dir, f"EmptyDir_{rel}.lnk")
                with self.preview_lock:
                    self.preview_log.append([d, "MIRROR (Empty Folder Link)", lnk_path, "Folder is empty"])
                self.logger.info(f"[預覽-空資料夾] 發現: {os.path.basename(d)}")
        else:
            # 實體執行
            empty_dirs = FSUtils.find_empty_folders(src_root, exclude_dirs={to_clean_dir})
            if empty_dirs:
                os.makedirs(to_clean_dir, exist_ok=True)
                for d in empty_dirs:
                    rel = os.path.relpath(d, src_root).replace(os.sep, "_")
                    lnk_path = os.path.join(to_clean_dir, f"EmptyDir_{rel}.lnk")
                    if self.shell_reader:
                        success = self.shell_reader.create_shortcut(lnk_path, d)
                        if success:
                            self.logger.info(f"[空資料夾捷徑] 建立捷徑: {os.path.basename(d)} → _ToClean/EmptyDir_{rel}.lnk")

    def confirm_cleanup(self):
        """讀取 _ToClean 目錄中的所有捷徑，解析並刪除它們所指向的真實實體檔案與資料夾"""
        to_clean_dir = os.path.join(self.config['src_root'], "_ToClean")
        if not os.path.exists(to_clean_dir):
            self.logger.warn("⚠️ 找不到待清理資料夾 (_ToClean)，無法執行刪除。")
            return
            
        self.logger.info("🚀 開始執行實體檔案與空資料夾清理...")
        
        # 啟動 ShellReader
        if self.shell_reader:
            self.shell_reader.start()
            
        try:
            lnk_files = []
            for r, d, f in os.walk(to_clean_dir):
                for file in f:
                    if file.lower().endswith(".lnk"):
                        lnk_files.append(os.path.join(r, file))
                        
            if not lnk_files:
                self.logger.info("ℹ️ _ToClean 資料夾內無任何捷徑，無需刪除。")
                # 嘗試清除空目錄
                try: os.rmdir(to_clean_dir)
                except: pass
                return
                
            deleted_count = 0
            deleted_dirs_count = 0
            
            # 先收集所有要刪除的檔案與資料夾
            targets_files = []
            targets_dirs = []
            
            for lnk in lnk_files:
                if self.shell_reader:
                    target = self.shell_reader.resolve_shortcut(lnk)
                    if target and os.path.exists(target):
                        if os.path.isdir(target):
                            targets_dirs.append(target)
                        else:
                            targets_files.append(target)
            
            # 正式執行實體刪除
            # 1. 刪除檔案
            for f_path in targets_files:
                try:
                    os.remove(f_path)
                    self.logger.info(f"[實體刪除] 已刪除檔案: {os.path.basename(f_path)}")
                    deleted_count += 1
                except Exception as e:
                    self.logger.error(f"❌ 刪除檔案失敗: {f_path} - {e}")
                    
            # 2. 刪除空資料夾 (按路徑長度降序排列，確保子目錄先被刪除，父目錄才能順利 rm)
            targets_dirs.sort(key=len, reverse=True)
            for d_path in targets_dirs:
                try:
                    # 再次確認是否為空，避免誤刪有內容的資料夾
                    if os.path.exists(d_path) and not os.listdir(d_path):
                        os.rmdir(d_path)
                        self.logger.info(f"[實體刪除] 已刪除空資料夾: {os.path.basename(d_path)}")
                        deleted_dirs_count += 1
                except Exception as e:
                    self.logger.error(f"❌ 刪除資料夾失敗: {d_path} - {e}")
                    
            # 3. 清理 _ToClean 資料夾本身
            try:
                # 刪除裡面的所有捷徑
                for lnk in lnk_files:
                    if os.path.exists(lnk):
                        os.remove(lnk)
                # 移除 _ToClean 目錄
                if os.path.exists(to_clean_dir) and not os.listdir(to_clean_dir):
                    os.rmdir(to_clean_dir)
            except Exception as e:
                self.logger.error(f"❌ 清理 _ToClean 資料夾失敗 - {e}")
                
            self.logger.info(f"=== ✅ 實體清理完成 ===\n共刪除 {deleted_count} 個螢幕截圖實體檔案，{deleted_dirs_count} 個空資料夾。")
            
        finally:
            if self.shell_reader:
                self.shell_reader.stop()

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
        class _Ctx: n = 0
        ctx = _Ctx()
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
                    ctx.n += 1
                    if ctx.n % 1000 == 0 and cb_status is not None:
                        cb_status(f"正在索引目標... ({ctx.n})")
                except Exception:
                    pass

    def _scan_files(self, root):
        files_list: list[str] = []
        total_size = 0
        class _Ctx: n = 0
        ctx = _Ctx()
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
                ctx.n += 1
                if ctx.n % 1000 == 0 and cb_status is not None:
                    cb_status(f"正在掃描... 已發現 {ctx.n} 個檔案")
        return files_list, int(total_size)

    def _process_single_file(self, file_path_raw, dst_root):
        file_path = str(file_path_raw)
        filename = str(os.path.basename(file_path))
        ext      = str(os.path.splitext(filename)[1]).lower()
        try:    f_size = os.path.getsize(file_path)
        except: f_size = 0

        # OneDrive 雲端防護檢查：如果檔案在雲端，則將 is_cloud 設為 True
        is_cloud = False
        if self.onedrive_protect:
            is_cloud = is_onedrive_cloud_only(file_path)

        if self.config['resume_enabled'] and self._is_processed(file_path, f_size):
            with self.stats_lock:
                self.stats['skipped'] += 1
                self.stats['processed_size'] += f_size
            return

        if ext in ConfigConstants.EXT_JUNK: return

        is_photo = ext in ConfigConstants.EXT_PHOTOS
        is_video = ext in ConfigConstants.EXT_VIDEOS

        # ---------------- 原地清理模式 (In-place Cleanup) ----------------
        if self.config['mode'] == 'cleanup':
            # 只處理照片或影片
            if not (is_photo or is_video): return
            
            is_screenshot = False
            # 1. 檔名關鍵字比對 (雲端與本機皆可安全執行)
            if any(kw in filename.lower() for kw in ConfigConstants.SCREENSHOT_KEYWORDS):
                is_screenshot = True
            # 2. 智慧截圖辨識
            elif self.config.get('smart_screenshot', False) and is_photo:
                # 2a. 若檔案在雲端，使用 ShellReader 無痛讀取，不觸發下載
                if is_cloud and self.shell_reader:
                    props = self.shell_reader.get_properties(file_path)
                    if props.get('success'):
                        width_str = props.get('width', '')
                        height_str = props.get('height', '')
                        model = props.get('model', '')
                        maker = props.get('maker', '')
                        # 1. 檔名拍照命名排除
                        lower_name = filename.lower()
                        ext = os.path.splitext(lower_name)[1]
                        if lower_name.startswith(('img', 'dsc', 'c360', 'mvimg')) and ext in {'.jpg', '.jpeg', '.heic', '.heif'}:
                            pass
                        else:
                            m_w = re.search(r'(\d+)', width_str)
                            m_h = re.search(r'(\d+)', height_str)
                            if m_w and m_h:
                                w = int(m_w.group(1))
                                h = int(m_h.group(1))
                                if w > 0 and h > 0:
                                    strict_mode = self.config.get('screenshot_strict_mode', True)
                                    if strict_mode:
                                        # 手機直向螢幕截圖特徵：高大於寬，且比例 >= 1.6
                                        # 排除條件：寬度大於 1440 (超出實體螢幕上限) 或有拍攝日期
                                        if h > w and (h / w) >= 1.6 and not model and not maker:
                                            if w <= 1440:
                                                is_screenshot = True
                                    else:
                                        # 寬鬆模式：只要沒有相機型號與製造商，全當作截圖
                                        if not model and not maker:
                                            is_screenshot = True
                # 2b. 若檔案在本機，直接以 EXIF 與長寬比分析
                elif not is_cloud:
                    strict_mode = self.config.get('screenshot_strict_mode', True)
                    if is_screenshot_by_exif_and_ratio(file_path, strict_mode=strict_mode):
                        is_screenshot = True
                    
            if is_screenshot:
                to_clean_dir = os.path.join(self.config['src_root'], "_ToClean")
                lnk_path = os.path.join(to_clean_dir, filename + ".lnk")
                if self.config.get('dry_run'):
                    with self.preview_lock:
                        self.preview_log.append([file_path, "MIRROR (Shortcut)", lnk_path, "Is screenshot"])
                    self.logger.info(f"[預覽-捷徑] 發現截圖: {filename} → _ToClean/{filename}.lnk")
                    with self.stats_lock:
                        self.stats['processed'] += 1
                        self.stats['processed_size'] += f_size
                else:
                    if self.shell_reader:
                        success = self.shell_reader.create_shortcut(lnk_path, file_path)
                        if success:
                            self.logger.info(f"[截圖捷徑] 建立捷徑: {filename} → _ToClean/{filename}.lnk")
                            with self.stats_lock:
                                self.stats['processed'] += 1
                                self.stats['processed_size'] += f_size
                            if self.config['resume_enabled']:
                                self._hist_update(file_path, "MIRRORED_SHORTCUT")
            return

        # ---------------- 一般整理模式 (Copy/Move) ----------------
        if not (is_photo or is_video): return

        # 0. 提前解析日期 (用於分類與隔離檔案命名)
        date_obj = self.date_parser.get_date(file_path, is_photo, is_cloud, self.shell_reader)
        if not date_obj:
            try:
                ctime = os.path.getctime(file_path)
                date_obj = datetime.datetime.fromtimestamp(ctime)
            except Exception:
                pass

        # 1. 螢幕截圖隔離
        is_screenshot = False
        if any(kw in filename.lower() for kw in ConfigConstants.SCREENSHOT_KEYWORDS):
            is_screenshot = True
        elif self.config.get('smart_screenshot', False) and is_photo:
            if is_cloud and self.shell_reader:
                props = self.shell_reader.get_properties(file_path)
                if props.get('success'):
                    width_str = props.get('width', '')
                    height_str = props.get('height', '')
                    # 1. 檔名拍照命名排除
                    lower_name = filename.lower()
                    ext = os.path.splitext(lower_name)[1]
                    if lower_name.startswith(('img', 'dsc', 'c360', 'mvimg')) and ext in {'.jpg', '.jpeg', '.heic', '.heif'}:
                        pass
                    else:
                        model = props.get('model', '')
                        maker = props.get('maker', '')
                        m_w = re.search(r'(\d+)', width_str)
                        m_h = re.search(r'(\d+)', height_str)
                        if m_w and m_h:
                            w = int(m_w.group(1))
                            h = int(m_h.group(1))
                            if w > 0 and h > 0:
                                strict_mode = self.config.get('screenshot_strict_mode', True)
                                if strict_mode:
                                    if h > w and (h / w) >= 1.6 and not model and not maker:
                                        if w <= 1440:
                                            is_screenshot = True
                                else:
                                    if not model and not maker:
                                        is_screenshot = True
            elif not is_cloud:
                strict_mode = self.config.get('screenshot_strict_mode', True)
                if is_screenshot_by_exif_and_ratio(file_path, strict_mode):
                    is_screenshot = True

        if is_screenshot:
            self._transfer_to(file_path, dst_root, "_Screenshots", filename, "截圖", date_obj)
            return

        # 2. 重複檔案去重 (將 is_cloud 傳入 check_dup)
        dupe = self._check_dup(file_path, f_size, is_cloud)
        if dupe in ("DEST_DUPE", "SRC_DUPE"):
            if self.config['mode'] == 'move':
                self._transfer_to(file_path, dst_root, "_Duplicates", filename, "重複", date_obj)
            else:
                self.logger.warn(f"[略過] 發現重複內容: {filename}")
                with self.stats_lock: self.stats['skipped'] += 1
                if self.config['resume_enabled'] and not self.config.get('dry_run'):
                    self._hist_update(file_path, f"SKIPPED_{dupe}")
                if self.config.get('dry_run'):
                    with self.preview_lock: self.preview_log.append([file_path, f"SKIP ({dupe})", "-", "Duplicate content"])
            return

        # 3. 模糊偵測 (如果是雲端預留檔案則跳過)
        if self.config['blur_check_enabled'] and is_photo and not is_cloud:
            is_blur, score = ImageOps.is_blurry(file_path)
            if is_blur:
                self._transfer_to(file_path, dst_root, "_Blurry", filename, f"模糊({int(score)})", date_obj)
                return

        # 5. 原況相片 (Live Photo) 配對判定 (若在雲端，os.path.exists 可能需要注意，但這是安全非內容讀取)
        is_live = False
        base_p = os.path.splitext(file_path)[0]
        check_exts = ConfigConstants.EXT_VIDEOS if is_photo else ConfigConstants.EXT_PHOTOS
        for e in check_exts:
            if os.path.exists(base_p + e) or os.path.exists(base_p + e.upper()):
                is_live = True
                break

        if date_obj:
            type_folder  = "_LivePhotos" if is_live else ("Photos" if is_photo else "Videos")
            pattern = self.config.get('folder_pattern', 'ym')
            if pattern == 'ymd':
                date_path = os.path.join(date_obj.strftime("%Y"), date_obj.strftime("%m-%d"))
            elif pattern == 'y':
                date_path = date_obj.strftime("%Y")
            else:
                date_path = os.path.join(date_obj.strftime("%Y"), date_obj.strftime("%m"))

            final_sub = os.path.join(date_path, type_folder)
            
            # GPS 分類 (雲端檔案不進行 GPS 解析)
            if self.config['gps_enabled'] and not is_cloud:
                loc = ImageOps.get_location_folder(file_path)
                if loc: final_sub = os.path.join(final_sub, loc)
                
            target_dir = os.path.join(dst_root, final_sub)
            if self.config['rename_enabled'] and not is_live:
                with self.naming_lock:
                    safe_reserved = self.dry_run_paths if self.config.get('dry_run') else set()
                    date_prefix = date_obj.strftime("%Y_%m_%d") if date_obj else "Unknown"
                    rename_mode = self.config.get('rename_mode', 'date_seq')
                    t = FSUtils.get_sequence_name(target_dir, date_prefix, ext, self.dir_counters, rename_mode, safe_reserved)
            else:
                if not self.config.get('dry_run'): os.makedirs(target_dir, exist_ok=True)
                with self.naming_lock:
                    safe_reserved = self.dry_run_paths if self.config.get('dry_run') else set()
                    t = FSUtils.get_unique_path(os.path.join(target_dir, filename), safe_reserved)
            self._execute(file_path, t, "整理")
        else:
            self._transfer_to(file_path, dst_root, "No_Date", filename, "整理")

    def _transfer_to(self, src, root, sub, name, tag, date_obj=None):
        d = os.path.join(root, sub)
        if not self.config.get('dry_run'): os.makedirs(d, exist_ok=True)
        ext = os.path.splitext(name)[1]
        with self.naming_lock:
            reserved = self.dry_run_paths if self.config.get('dry_run') else None
            if self.config.get('rename_enabled'):
                rename_mode = self.config.get('rename_mode', 'date_seq')
                prefix_map = {
                    "_Duplicates": "DUP",
                    "_Screenshots": "Shot",
                    "_Blurry": "Blur",
                    "No_Date": "NoDate"
                }
                base_pref = prefix_map.get(sub, "File")
                if date_obj and rename_mode == "date_seq":
                    pref = f"{base_pref}_{date_obj.strftime('%Y_%m_%d')}"
                else:
                    pref = base_pref
                t = FSUtils.get_sequence_name(d, pref, ext, self.dir_counters, rename_mode, reserved)
            else:
                t = FSUtils.get_unique_path(os.path.join(d, name), reserved)
        self._execute(src, t, tag)

    def _execute(self, src, dst, tag):
        if os.path.abspath(src) == os.path.abspath(dst):
            self.logger.info(f"[{tag}] 已在正確位置: {os.path.basename(src)}")
            with self.stats_lock:
                self.stats['skipped'] += 1
            return

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
        if self.config['mode'] in ('move', 'cleanup'):
            try:
                shutil.move(src, dst)
                self.logger.info(f"[{tag}] 移動: {os.path.basename(src)} → {parent}/{os.path.basename(dst)}")
            except PermissionError as e:
                self.logger.error(f"❌ 移動失敗 (權限不足，可能正由 OneDrive 同步中被鎖定): {os.path.basename(src)}")
                raise
        else:
            try:
                shutil.copy2(src, dst)
                self.logger.info(f"[{tag}] 複製: {os.path.basename(src)} → {parent}/{os.path.basename(dst)}")
            except PermissionError as e:
                self.logger.error(f"❌ 複製失敗 (權限不足，可能正由 OneDrive 同步中被鎖定): {os.path.basename(src)}")
                raise
        with self.stats_lock:
            self.stats['processed'] += 1
            try: self.stats['processed_size'] += os.path.getsize(dst)
            except Exception: pass
        if self.config['resume_enabled']: self._hist_update(src, dst)

    def _check_dup(self, path, f_size, is_cloud=False):
        # 雲端隨選檔案降級去重邏輯：100% 避免計算雜湊觸發下載
        if is_cloud:
            filename = os.path.basename(path)
            # 雲端去重降級：我們以檔案大小與檔名作為 seen_files 鍵值比對
            with self.dedup_lock:
                key = (f_size, filename)
                if key in self.seen_files:
                    return "SRC_DUPE"
                self.seen_files[key] = path
                return None

        f_p = f_f = None
        if self.config.get('skip_existing') and f_size in self.dst_index:
            source_set = getattr(self, 'source_files_set', set())
            for dp in self.dst_index[f_size]:
                abs_dp = os.path.abspath(dp)
                if os.path.abspath(path) == abs_dp: continue
                if abs_dp in source_set: continue
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
                # 定時背景存檔：每累積 50 筆紀錄存一次檔，防範意外關閉/當機導致進度完全遺失
                if len(self.history_db) % 50 == 0:
                    with open(ConfigConstants.HISTORY_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self.history_db, f)
        except Exception: pass

    def _is_processed(self, src, size):
        with self.history_lock:
            if src not in self.history_db: return False
            rec = self.history_db[src]
        try:
            if abs(os.path.getmtime(src) - rec['mtime']) > 2.0 or size != rec['size']: return False
            if self.config.get('mode') == 'move' and rec.get('dest') in ("SKIPPED_DEST_DUPE", "SKIPPED_SRC_DUPE"):
                return False
            if rec['dest'] not in ("SKIPPED_DEST_DUPE", "SKIPPED_SRC_DUPE") and not os.path.exists(str(rec['dest'])): return False
            return True
        except Exception: return False


# ==============================================================================
# 模組八.五：SystemTrayManager (系統列托盤圖示管理器)
# ==============================================================================
class SystemTrayManager:
    """系統列托盤圖示管理器 (System Tray Manager)"""
    def __init__(self, bridge):
        self.bridge = bridge
        self.icon = None
        self.window = None
        self._lock = threading.Lock()

    def _create_icon_image(self):
        img = Image.new('RGBA', (64, 64), color=(15, 23, 42, 255))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(30, 41, 59, 255), outline=(56, 189, 248, 255), width=3)
        draw.rectangle((16, 26, 48, 48), fill=(56, 189, 248, 255))
        draw.polygon([(16, 26), (24, 16), (40, 16), (48, 26)], fill=(56, 189, 248, 255))
        draw.ellipse((26, 31, 38, 43), fill=(15, 23, 42, 255))
        return img

    def minimize(self, window):
        self.window = window
        # 1. 優先進行標準縮小，確保不會發生視窗憑空消失的狀況
        try:
            window.minimize()
        except Exception:
            pass

        with self._lock:
            if self.icon is not None:
                try: window.hide()
                except Exception: pass
                return

            try:
                import pystray
                from pystray import MenuItem as item

                icon_img = self._create_icon_image()
                menu = pystray.Menu(
                    item('📌 開啟主視窗', self.restore),
                    item('❌ 結束程式', self.exit_app)
                )
                self.icon = pystray.Icon("SmartPhotoOrganizer", icon_img, f"{ConfigConstants.APP_NAME} (背景整理中)", menu)
                self.icon.default_action = self.restore
                
                def _run_icon():
                    try:
                        self.icon.run()
                    except Exception as err:
                        Logger.get_instance().error(f"系統列圖示異常: {err}")
                        self.restore()

                threading.Thread(target=_run_icon, daemon=True).start()
                
                # 託盤圖示啟動後隱藏主視窗
                try: window.hide()
                except Exception: pass
                
                try:
                    self.icon.notify("已縮小至右下角系統列 (若未看到，請點擊右下角 ^ 箭頭展開)", f"{ConfigConstants.APP_NAME}")
                except Exception:
                    pass
            except Exception as e:
                Logger.get_instance().error(f"無法建立系統列圖示，退回標準縮小: {e}")
                try: window.minimize()
                except Exception: pass

    def restore(self, icon=None, item=None):
        if self.window:
            try:
                self.window.show()
                self.window.restore()
            except Exception:
                pass
        with self._lock:
            if self.icon:
                try:
                    self.icon.stop()
                except Exception:
                    pass
                self.icon = None

    def exit_app(self, icon=None, item=None):
        if self.bridge and self.bridge._processor:
            self.bridge._processor.stop()
        self.restore()
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
        os._exit(0)


# ==============================================================================
# 模組九：WebBridge & Web UI 啟動器 (PyWebView)
# ==============================================================================
class WebBridge:
    def __init__(self):
        self._app_config = AppConfig.get_instance()
        self._logger     = Logger.get_instance()
        self._processor: Any = None
        self._window: Any = None
        self._tray_manager = SystemTrayManager(self)
        
        self._log_queue = []
        self._latest_progress = None
        self._process_finished_msg = None
        self._queue_lock = threading.Lock()
        
        self._logger.set_callback(self._on_log)

    def set_window(self, window):
        self._window = window

    def minimize_to_tray(self):
        if self._window:
            self._tray_manager.minimize(self._window)

    def get_initial_config(self):
        return {
            "source_dir": self._app_config.source_dir,
            "dest_dir": self._app_config.dest_dir,
            "skip_existing": bool(self._app_config.skip_existing),
            "folder_pattern": getattr(self._app_config, 'folder_pattern', 'ym'),
            "rename_mode": getattr(self._app_config, 'rename_mode', 'date_seq')
        }

    def get_updates(self):
        with self._queue_lock:
            logs = list(self._log_queue)
            self._log_queue.clear()
            prog = self._latest_progress
            fin_msg = self._process_finished_msg
            self._process_finished_msg = None

        return {
            "logs": logs,
            "progress": prog,
            "finished_msg": fin_msg
        }

    def _get_dialog_type(self):
        if hasattr(webview, 'FileDialog') and hasattr(webview.FileDialog, 'FOLDER'):
            return webview.FileDialog.FOLDER
        return getattr(webview, 'FOLDER_DIALOG', 10)

    def select_source_folder(self):
        if not self._window: return ""
        try:
            res = self._window.create_file_dialog(self._get_dialog_type())
            if res and len(res) > 0:
                return res[0]
        except Exception as e:
            self._logger.error(f"選擇資料夾失敗: {e}")
        return ""

    def select_dest_folder(self):
        if not self._window: return ""
        try:
            res = self._window.create_file_dialog(self._get_dialog_type())
            if res and len(res) > 0:
                return res[0]
        except Exception as e:
            self._logger.error(f"選擇資料夾失敗: {e}")
        return ""

    def open_dest_folder(self, folder_path=None):
        target = folder_path.strip() if (folder_path and isinstance(folder_path, str)) else self._app_config.dest_dir
        if not target or not os.path.exists(target):
            target = self._app_config.source_dir
        if target and os.path.exists(target):
            try:
                os.startfile(target)
                return {"success": True}
            except Exception as e:
                return {"error": str(e)}
        return {"error": "資料夾不存在！"}

    def start_process(self, config_dict):
        src = config_dict.get('source_dir', '').strip()
        dst = config_dict.get('dest_dir', '').strip()
        mode = config_dict.get('mode', 'copy')

        if not src or not os.path.exists(src):
            return {"error": "來源資料夾不存在或未設定！"}
        if mode != 'cleanup' and not dst:
            return {"error": "請選擇目標資料夾！"}

        self._app_config.source_dir = src
        self._app_config.dest_dir = dst
        self._app_config.skip_existing = config_dict.get('skip_existing', False)
        self._app_config.folder_pattern = config_dict.get('folder_pattern', 'ym')
        self._app_config.rename_mode = config_dict.get('rename_mode', 'date_seq')
        self._app_config.save()

        cfg = {
            'src_root': src,
            'dst_root': dst,
            'mode': mode,
            'clean_empty': config_dict.get('clean_empty', False),
            'rename_enabled': config_dict.get('rename_enabled', False),
            'rename_mode': config_dict.get('rename_mode', 'date_seq'),
            'gps_enabled': config_dict.get('gps_enabled', False),
            'resume_enabled': config_dict.get('resume_enabled', True),
            'blur_check_enabled': config_dict.get('blur_check_enabled', False),
            'skip_existing': config_dict.get('skip_existing', False),
            'dry_run': config_dict.get('dry_run', False),
            'smart_screenshot': config_dict.get('smart_screenshot', True),
            'screenshot_strict_mode': config_dict.get('screenshot_strict_mode', True),
            'onedrive_protect': config_dict.get('onedrive_protect', True),
            'folder_pattern': config_dict.get('folder_pattern', 'ym')
        }

        self._processor = Processor(cfg, progress_callback=self._on_progress, status_callback=self._on_status)
        threading.Thread(target=self._run_processor, daemon=True).start()
        return {"success": True}

    def _run_processor(self):
        try:
            r = self._processor.start()
            self._on_log("=== ✅ 任務完成 ===", "info")
            msg = f"整理完成！\n已處理: {r['processed']}\n跳過: {r['skipped']}\n錯誤: {r['errors']}"
            with self._queue_lock:
                self._process_finished_msg = msg
        except Exception as e:
            self._on_log(f"❌ 執行失敗: {e}", "error")
            with self._queue_lock:
                self._process_finished_msg = f"執行失敗: {e}"

    def pause_process(self):
        if self._processor:
            self._processor.pause()
            self._on_log(">> ⏸ 任務已暫停", "warn")

    def resume_process(self):
        if self._processor:
            self._processor.resume()
            self._on_log(">> ▶️ 任務繼續", "info")

    def stop_process(self):
        if self._processor:
            self._processor.stop()
            self._on_log(">> ⏹ 正在停止任務...", "warn")

    def _on_progress(self, data):
        with self._queue_lock:
            self._latest_progress = data

    def _on_status(self, msg):
        pass

    def _on_log(self, msg, level='info'):
        with self._queue_lock:
            self._log_queue.append({"msg": msg, "level": level})


# ==============================================================================
# 程式入口
# ==============================================================================
if __name__ == "__main__":
    bridge = WebBridge()
    html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    window = webview.create_window(
        title=f"{ConfigConstants.APP_NAME} v{ConfigConstants.VERSION}",
        url=html_file,
        js_api=bridge,
        width=1020,
        height=900,
        resizable=True
    )
    bridge.set_window(window)
    webview.start(http_server=True, debug=False)

