# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer 媒體與檔案類型定義模組 (v3.0 單一副檔名來源)
提供專案內全模組 (main, takeout_zip, media_metadata, sidecar_matcher) 共享的媒體、照片、影片與廢棄檔副檔名集合。
"""

from typing import Set

# 相片副檔名集合 (包含原生相機、常見圖檔與所有 RAW 格式)
EXT_PHOTOS: Set[str] = {
    '.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.bmp', '.tiff', '.raw', '.arw', '.cr2', '.nef',
    '.cr3', '.dng', '.orf', '.rw2', '.pef', '.sr2'
}

# 影片副檔名集合 (包含常見影片與串流容器格式)
EXT_VIDEOS: Set[str] = {
    '.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v'
}

# 媒體副檔名總集 (相片 + 影片)
EXT_MEDIA: Set[str] = EXT_PHOTOS | EXT_VIDEOS

# 系統與輔助廢棄檔副檔名集合
EXT_JUNK: Set[str] = {
    '.json', '.ini', '.db', '.html', '.txt', '.tmp', '.url'
}
