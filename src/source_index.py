# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 1 - 唯讀來源索引模組 (source_index.py)
提供一般資料夾 (FolderSourceIndexer) 與 Takeout ZIP (TakeoutSourceIndexer) 的統一唯讀來源索引介面。
"""

import os
import stat
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Set
from media_types import EXT_MEDIA, EXT_PHOTOS, EXT_VIDEOS, EXT_JUNK
from takeout_zip import TakeoutZipScanner, ZipSecurityError


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point_or_link(path: str) -> bool:
    """
    檢查指定路徑是否為 Symlink、Windows Junction 或 Reparse Point。
    """
    if os.path.islink(path):
        return True
    try:
        st = os.lstat(path)
        if hasattr(st, 'st_file_attributes') and (st.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT):
            return True
        if stat.S_ISLNK(st.st_mode):
            return True
    except (OSError, AttributeError):
        pass
    return False


@dataclass
class SourceItem:
    """統一來源項目資料結構 (唯讀索引條目)"""
    source_key: str           # 任務內穩定且唯一的識別 key
    source_type: str          # "FOLDER" 或 "TAKEOUT_ZIP"
    logical_path: str         # 統一使用 "/" 的相對邏輯路徑 (例如 "Album2018/photo.jpg")
    filename: str             # 原始檔名 (例如 "photo.jpg")
    extension: str            # 小寫副檔名含點 (例如 ".jpg")
    size: int                 # 檔案容量 (位元組)
    is_media: bool            # 是否為相片或影片媒體
    is_json: bool             # 是否為 Sidecar JSON 檔
    is_safe: bool = True      # 是否通過安全驗證
    reject_reason: Optional[str] = None

    # 一般資料夾 (FOLDER) 專屬屬性
    abs_path: Optional[str] = None

    # Takeout ZIP 專屬屬性
    archive_path: Optional[str] = None        # ZIP 實體路徑
    archive_fingerprint: Optional[str] = None # 封存檔指紋
    member_index: Optional[int] = None        # ZIP 成員索引
    member_crc: Optional[int] = None          # ZIP 成員 CRC32
    archive_member_name: Optional[str] = None # ZIP 中央目錄原始名稱（供解壓雙重核對）


class FolderSourceIndexer:
    """一般資料夾唯讀索引器"""

    # 專案管理與系統隱藏資料夾排除清單 (不區分大小寫)
    EXCLUDED_DIR_NAMES: Set[str] = {
        '_excluded', '_review', '_reviewcache', '_quarantine', '_importtemp',
        '.git', '.svn', '$recycle.bin', 'system volume information'
    }

    @classmethod
    def index_folder(cls, root_dir: str) -> List[SourceItem]:
        """
        唯讀掃描一般資料夾，建立 SourceItem 列表。
        規則：
        1. 使用 media_types.py 作為副檔名唯一來源。
        2. 排除專案管理目錄 (_Review, _Quarantine, _ImportTemp 等)。
        3. 不跟隨 Symlink / Junction / Reparse Point。
        4. 保留原始中文/Unicode 檔名與路徑，logical_path 統一採用 "/"。
        """
        if not root_dir or not os.path.exists(root_dir):
            return []

        norm_root = os.path.abspath(root_dir)
        items: List[SourceItem] = []

        for current_root, dirs, files in os.walk(norm_root, topdown=True, followlinks=False):
            # 1. 檢查並排除專案管理與系統資料夾、Symlink 及 Reparse Point/Junction
            dirs[:] = [
                d for d in dirs
                if d.lower() not in cls.EXCLUDED_DIR_NAMES
                and not is_reparse_point_or_link(os.path.join(current_root, d))
            ]

            for fname in files:
                abs_p = os.path.join(current_root, fname)

                # 2. 不跟隨 Symlink / Junction / Reparse Point
                if is_reparse_point_or_link(abs_p):
                    continue

                rel_p = os.path.relpath(abs_p, norm_root).replace('\\', '/').strip('/')
                ext = os.path.splitext(fname)[1].lower()

                try:
                    st_size = os.path.getsize(abs_p)
                except OSError:
                    st_size = 0

                is_media = ext in EXT_MEDIA
                is_json = (ext == '.json')

                item = SourceItem(
                    source_key=f"folder:{rel_p.lower()}",
                    source_type="FOLDER",
                    logical_path=rel_p,
                    filename=fname,
                    extension=ext,
                    size=st_size,
                    is_media=is_media,
                    is_json=is_json,
                    is_safe=True,
                    abs_path=abs_p
                )
                items.append(item)

        # 排序保持決定性輸出
        items.sort(key=lambda x: x.source_key)
        return items


class TakeoutSourceIndexer:
    """Takeout ZIP 唯讀來源索引器 (包裝 TakeoutZipScanner.scan_archive 中央目錄結果，絕不解壓媒體)"""

    @classmethod
    def index_archives(cls, zip_paths: List[str]) -> List[SourceItem]:
        """
        唯讀掃描一或多個 Takeout ZIP 封存檔中央目錄。
        使用 TakeoutZipScanner.scan_archive 嚴格校驗與讀取。
        """
        if not zip_paths:
            return []

        all_items: List[SourceItem] = []

        for zip_p in zip_paths:
            if not zip_p or not os.path.exists(zip_p):
                raise ZipSecurityError(f"ZIP 封存檔路徑不存在: {zip_p}")

            fp = TakeoutZipScanner.get_archive_fingerprint(zip_p)
            scanned_members = TakeoutZipScanner.scan_archive(zip_p)

            for m in scanned_members:
                fname = m["filename"]
                ext = os.path.splitext(fname)[1].lower()
                rel_p = m["normalized_path"]

                item = SourceItem(
                    source_key=f"zip:{fp}:{m['member_index']}",
                    source_type="TAKEOUT_ZIP",
                    logical_path=rel_p,
                    filename=fname,
                    extension=ext,
                    size=m["uncompressed_size"],
                    is_media=m["is_media"],
                    is_json=m["is_json"],
                    is_safe=m["is_safe"],
                    reject_reason=m.get("reject_reason"),
                    archive_path=os.path.abspath(zip_p),
                    archive_fingerprint=fp,
                    member_index=m["member_index"],
                    member_crc=m["member_crc"],
                    archive_member_name=m["member_name"]
                )
                all_items.append(item)

        # 排序保持決定性輸出
        all_items.sort(key=lambda x: (x.archive_fingerprint or '', x.member_index or 0))
        return all_items
