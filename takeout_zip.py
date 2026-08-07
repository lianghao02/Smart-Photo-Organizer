# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - ZIP 掃描、ZipInfo 唯讀讀取與單檔按需串流解壓模組 (v2.1 Phase 2.1 嚴謹修補版)
修復按 member_index 檢索、排他建立 .part (xb)、磁碟空間預檢與安全更名。
"""

import os
import zlib
import shutil
import zipfile
import hashlib
from typing import Tuple, Optional, Dict, Any, List, Callable


class ZipSecurityError(Exception):
    """ZIP 資訊安全檢查失敗例外"""
    pass


class ZipExtractionError(Exception):
    """ZIP 成員解壓或完整性校驗失敗例外"""
    pass


class TakeoutZipScanner:
    # 限制條件 (Configurable Safety Thresholds)
    MAX_JSON_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
    MAX_COMPRESSION_RATIO = 1000.0          # 1000:1 Zip Bomb
    MAX_MEMBER_COUNT_PER_ZIP = 1_000_000    # 1,000,000 單 ZIP 成員上限
    MAX_JOB_TOTAL_MEMBERS = 1_000_000       # 1,000,000 全任務總成員上限
    MAX_ZIP_COUNT = 500                    # 500 ZIP 檔上限
    CHUNK_SIZE = 64 * 1024                 # 64 KB 串流區塊

    # 支援的解壓方法
    SUPPORTED_COMPRESS_TYPES = {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
        zipfile.ZIP_BZIP2,
        zipfile.ZIP_LZMA,
    }

    @staticmethod
    def get_archive_fingerprint(zip_path: str) -> str:
        """計算封存檔指紋 (絕對路徑 + 大小 + mtime)"""
        st = os.stat(zip_path)
        raw = f"{os.path.abspath(zip_path)}_{st.st_size}_{st.st_mtime}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

    @classmethod
    def validate_zip_info(cls, info: zipfile.ZipInfo) -> Tuple[bool, Optional[str]]:
        """
        審查單一 ZipInfo 成員之資訊安全性
        拒絕：絕對路徑、磁碟代號、UNC路徑、.. 路徑穿越、符號連結、加密成員、不支援的壓縮法、非空零壓縮容量與 Zip Bomb。
        """
        filename = info.filename

        # 1. 拒絕絕對路徑、磁碟代號 (C:\) 與 UNC 路徑 (\\)
        if filename.startswith('/') or filename.startswith('\\'):
            return False, f"危險路徑 (開頭斜線): {filename}"
        if len(filename) >= 2 and filename[1] == ':':
            return False, f"危險路徑 (磁碟代號): {filename}"
        if filename.startswith(r'\\'):
            return False, f"危險路徑 (UNC路徑): {filename}"

        # 2. 拒絕 .. 上層目錄穿越
        parts = filename.replace('\\', '/').split('/')
        if '..' in parts:
            return False, f"危險路徑 (路徑穿越 ..): {filename}"

        # 3. 拒絕符號連結 (Symlinks)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            return False, f"不支援符號連結成員: {filename}"

        # 4. 拒絕加密成員
        if info.flag_bits & 0x1:
            return False, f"不支援加密成員: {filename}"

        # 5. 檢查壓縮方法支援度
        if info.compress_type not in cls.SUPPORTED_COMPRESS_TYPES:
            return False, f"不支援的壓縮方法 ({info.compress_type}): {filename}"

        # 6. 檢查單一 JSON 大小限制 (10 MB)
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.json' and info.file_size > cls.MAX_JSON_SIZE_BYTES:
            return False, f"JSON 成員超過 10MB 限制: {info.file_size} bytes"

        # 7. 非空成員解壓大於 0 但壓縮大小等於 0 判定為損毀，全部拒絕
        if info.file_size > 0:
            if info.compress_size == 0:
                return False, f"異常損毀成員 (非空檔案壓縮大小為 0): {filename}"
            ratio = info.file_size / float(info.compress_size)
            if ratio > cls.MAX_COMPRESSION_RATIO:
                return False, f"潛在 Zip Bomb 攻擊 (壓縮比 {ratio:.1f}:1): {filename}"

        return True, None

    @classmethod
    def scan_archive(cls, zip_path: str) -> List[Dict[str, Any]]:
        """
        以唯讀模式開啟 ZIP，掃描中央目錄成員
        回傳通過安全檢查的成員清單
        """
        if not zipfile.is_zipfile(zip_path):
            raise ZipSecurityError(f"檔案非合法 ZIP 格式或損毀: {zip_path}")

        members = []
        with zipfile.ZipFile(zip_path, 'r') as zf:
            infolist = zf.infolist()
            if len(infolist) > cls.MAX_MEMBER_COUNT_PER_ZIP:
                raise ZipSecurityError(f"ZIP 成員數 ({len(infolist)}) 超過安全上限 {cls.MAX_MEMBER_COUNT_PER_ZIP}")

            for idx, info in enumerate(infolist):
                # 跳過目錄 entry
                if info.is_dir() or info.filename.endswith('/') or info.filename.endswith('\\'):
                    continue

                is_safe, reason = cls.validate_zip_info(info)
                fname = os.path.basename(info.filename)
                ext = os.path.splitext(fname)[1].lower()

                member_item = {
                    "member_index": idx,
                    "member_name": info.filename,
                    "filename": fname,
                    "normalized_path": info.filename.replace('\\', '/').strip('/'),
                    "member_crc": info.CRC,
                    "uncompressed_size": info.file_size,
                    "compressed_size": info.compress_size,
                    "is_safe": is_safe,
                    "reject_reason": reason,
                    "is_json": ext == '.json',
                    "is_media": ext in (
                        '.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.bmp', '.tiff', '.raw', '.arw', '.cr2', '.nef',
                        '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.m4v', '.3gp'
                    )
                }
                members.append(member_item)

        return members

    @classmethod
    def extract_member_stream(
        cls,
        zip_path: str,
        member_index: int,
        part_path: str,
        cancel_check_func: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        單一成員依 member_index 進行按需串流解壓至 part_path
        - 使用排他模式 ('xb') 開啟暫存檔，防止覆寫既有檔案
        - 解壓前檢查剩餘磁碟空間
        - 邊寫入邊同步計算 CRC32 與 SHA-256
        - 完成後進行 flush + fsync 寫入實體磁碟
        - 發生例外或使用者取消時自動清理暫存檔
        """
        target_dir = os.path.dirname(os.path.abspath(part_path))
        os.makedirs(target_dir, exist_ok=True)

        sha256 = hashlib.sha256()
        crc32_val = 0
        bytes_written = 0

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                infolist = zf.infolist()
                if member_index < 0 or member_index >= len(infolist):
                    raise ZipExtractionError(f"member_index 超出範圍 ({member_index} / {len(infolist)})")

                info = infolist[member_index]

                # 磁碟剩餘空間檢查 (至少需要 uncompressed_size * 2 + 100MB 緩衝)
                usage = shutil.disk_usage(target_dir)
                required_space = info.file_size * 2 + (100 * 1024 * 1024)
                if usage.free < required_space:
                    raise ZipExtractionError(f"磁碟空間不足 (剩餘 {usage.free / (1024**2):.1f}MB < 需要 {required_space / (1024**2):.1f}MB)")

                # 排他建立模式 'xb' 避免覆寫
                with zf.open(info, 'r') as source_stream:
                    with open(part_path, 'xb') as target_file:
                        while True:
                            if cancel_check_func and cancel_check_func():
                                raise ZipExtractionError("使用者取消匯入任務")

                            chunk = source_stream.read(cls.CHUNK_SIZE)
                            if not chunk:
                                break
                            target_file.write(chunk)
                            sha256.update(chunk)
                            crc32_val = zlib.crc32(chunk, crc32_val)
                            bytes_written += len(chunk)

                        # 落碟刷寫
                        target_file.flush()
                        os.fsync(target_file.fileno())

                # 校驗輸出容量與 CRC32
                computed_crc = crc32_val & 0xFFFFFFFF
                if bytes_written != info.file_size:
                    raise ZipExtractionError(f"解壓容量不合 (實際 {bytes_written} vs 宣告 {info.file_size}): idx={member_index}")
                if computed_crc != (info.CRC & 0xFFFFFFFF):
                    raise ZipExtractionError(f"CRC32 校驗失敗 (實際 0x{computed_crc:08X} vs 宣告 0x{info.CRC & 0xFFFFFFFF:08X}): idx={member_index}")

            return {
                "sha256": sha256.hexdigest(),
                "bytes_written": bytes_written,
                "crc32": computed_crc
            }

        except Exception as e:
            # 發生例外時，確保刪除殘留之不完整 .part 暫存檔
            if os.path.exists(part_path):
                try: os.remove(part_path)
                except OSError: pass
            raise ZipExtractionError(f"串流解壓失敗 [member_index={member_index}]: {e}")
