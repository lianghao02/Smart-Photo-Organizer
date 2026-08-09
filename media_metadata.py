# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 媒體 Metadata 解析與日期決策模組 (v4.0 Phase 4 異常隔離版)
讀取 .part 暫存檔之 EXIF、ffprobe 與 Sidecar JSON，計算 _Review/DateConflict、_Review/LowConfidenceDate 與 _Excluded/Screenshots 隔離路徑。
"""

import os
import json
import datetime
from typing import Optional, Dict, Any


class MediaMetadataExtractor:
    # 共用照片副檔名集合 (包含所有相機原生與 RAW 格式)
    EXT_PHOTOS = {
        '.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.bmp', '.tiff', '.raw', '.arw', '.cr2', '.nef',
        '.cr3', '.dng', '.orf', '.rw2', '.pef', '.sr2'
    }

    @staticmethod
    def parse_sidecar_json_bytes(json_bytes: bytes) -> Optional[dict]:
        """從 Sidecar JSON 位元組解析 photoTakenTime 或 creationTime 數據"""
        if not json_bytes:
            return None
        try:
            data = json.loads(json_bytes.decode('utf-8', errors='ignore'))
            taken_time = data.get('photoTakenTime', {})
            ts = taken_time.get('timestamp')
            if ts:
                return {"timestamp": int(ts), "formatted": taken_time.get('formatted', '')}
            
            creation_time = data.get('creationTime', {})
            ts = creation_time.get('timestamp')
            if ts:
                return {"timestamp": int(ts), "formatted": creation_time.get('formatted', '')}
        except Exception:
            pass
        return None

    @classmethod
    def is_screenshot_filename(cls, filename: str) -> bool:
        """檔名特徵捷徑判斷是否為截圖"""
        fn_lower = filename.lower()
        patterns = ('screenshot', 'screen_shot', '螢幕快照', '螢幕截圖', '截圖', 'line_album_')
        return any(p in fn_lower for p in patterns)

    @classmethod
    def resolve_media_date_and_destination(
        cls,
        part_path: str,
        filename: str,
        dst_root: str,
        date_parser: Any,
        json_data: Optional[dict] = None,
        folder_pattern: str = "ym",
        rename_mode: str = "date_seq",
        smart_screenshot: bool = True
    ) -> Dict[str, Any]:
        """
        針對 .part 暫存檔解析 EXIF/ffprobe Metadata，整合 Sidecar JSON 呼叫 DateParser 進行日期決策
        並依據 DateConflict、LowConfidenceDate 與 Screenshots 進行階層式異常隔離。
        """
        orig_ext = os.path.splitext(filename)[1].lower()
        is_photo = orig_ext in cls.EXT_PHOTOS
        sub_type_folder = "Photos" if is_photo else "Videos"

        # 1. 檔名截圖識別
        is_screenshot = smart_screenshot and cls.is_screenshot_filename(filename)

        # 2. 轉換 Sidecar JSON UTC 時間為帶時區偏移 (+00:00 / Z) 的 ISO 8601 字串
        google_json_date = None
        if json_data and 'timestamp' in json_data:
            try:
                dt = datetime.datetime.fromtimestamp(json_data['timestamp'], datetime.timezone.utc)
                google_json_date = dt.isoformat()
            except Exception:
                pass

        # 3. 呼叫 DateParser 取得日期細節與衝突標記
        details = date_parser.get_date_details(
            part_path,
            is_photo=is_photo,
            is_cloud=False,
            shell_reader=None,
            google_json_date=google_json_date
        )
        parsed_dt = details.get("date")
        confidence = details.get("confidence", 0)
        source_tag = details.get("source", "未知")
        has_conflict = details.get("conflict", False)

        if parsed_dt:
            date_str = parsed_dt.strftime('%Y-%m-%d')
            year_str = parsed_dt.strftime('%Y')
            month_str = parsed_dt.strftime('%m')
        else:
            date_str = None
            year_str = "No_Date"
            month_str = "No_Date"

        # 4. Phase 4 階層式異常隔離路徑計算
        if is_screenshot:
            # 截圖隔離
            target_subfolder = os.path.join(dst_root, "_Excluded", "Screenshots")
        elif has_conflict:
            # EXIF 與 Sidecar JSON 日期衝突隔離
            target_subfolder = os.path.join(dst_root, "_Review", "DateConflict", year_str, sub_type_folder)
        elif confidence < 60:
            # 低可信度日期隔離
            target_subfolder = os.path.join(dst_root, "_Review", "LowConfidenceDate", year_str, sub_type_folder)
        elif year_str == "No_Date":
            target_subfolder = os.path.join(dst_root, "No_Date", sub_type_folder)
        elif folder_pattern == "y":
            target_subfolder = os.path.join(dst_root, year_str, sub_type_folder)
        else:
            target_subfolder = os.path.join(dst_root, year_str, month_str, sub_type_folder)

        return {
            "date_str": date_str,
            "date_source": source_tag,
            "confidence": confidence,
            "target_dir": target_subfolder,
            "parsed_dt": parsed_dt,
            "is_photo": is_photo,
            "has_conflict": has_conflict,
            "is_screenshot": is_screenshot
        }
