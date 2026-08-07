# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 媒體 Metadata 解析與日期決策模組 (v3.1 API 契合法版)
讀取 .part 暫存檔之 EXIF、ffprobe 與 Sidecar JSON，與 DateParser 的 get_date_details 介面無縫整合。
"""

import os
import json
import datetime
from typing import Optional, Dict, Any


class MediaMetadataExtractor:
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
    def resolve_media_date_and_destination(
        cls,
        part_path: str,
        filename: str,
        dst_root: str,
        date_parser: Any,
        json_data: Optional[dict] = None,
        folder_pattern: str = "ym",
        rename_mode: str = "date_seq"
    ) -> Dict[str, Any]:
        """
        針對 .part 暫存檔解析 EXIF/ffprobe Metadata，整合 Sidecar JSON 呼叫 DateParser.get_date_details() 進行日期決策
        回傳最佳日期候選、置信度與與 Processor 一致的年/月/Photos|Videos 目標資料夾路徑。
        """
        orig_ext = os.path.splitext(filename)[1].lower()
        is_photo = orig_ext in (
            '.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.bmp', '.tiff', '.raw', '.arw', '.cr2', '.nef'
        )
        sub_type_folder = "Photos" if is_photo else "Videos"

        # 呼叫專案核心 DateParser 的 get_date_details 方法
        details = date_parser.get_date_details(part_path, is_photo=is_photo)
        parsed_dt = details.get("date")
        confidence = details.get("confidence", 0)
        source_tag = details.get("source", "未知")

        # 若有 Sidecar JSON 時間且其可信度較高或作為參考
        if json_data and 'timestamp' in json_data:
            try:
                json_dt = datetime.datetime.fromtimestamp(json_data['timestamp'], datetime.timezone.utc)
                # 當現有 EXIF 無日期或可信度低於 Google Takeout JSON (75 分) 時採納
                if not parsed_dt or confidence < 75:
                    parsed_dt = json_dt.replace(tzinfo=None)
                    source_tag = "Google Takeout JSON"
                    confidence = 75
            except Exception:
                pass

        if parsed_dt:
            date_str = parsed_dt.strftime('%Y-%m-%d')
            year_str = parsed_dt.strftime('%Y')
            month_str = parsed_dt.strftime('%m')
        else:
            date_str = None
            year_str = "No_Date"
            month_str = "No_Date"

        # 根據 folder_pattern 計算與主 Processor 一致的標頭資料夾結構 (年/月/Photos|Videos)
        if year_str == "No_Date":
            target_subfolder = os.path.join(dst_root, "No_Date", sub_type_folder)
        elif folder_pattern == "y":
            target_subfolder = os.path.join(dst_root, year_str, sub_type_folder)
        elif folder_pattern == "ym":
            target_subfolder = os.path.join(dst_root, year_str, month_str, sub_type_folder)
        else:
            target_subfolder = os.path.join(dst_root, year_str, month_str, sub_type_folder)

        return {
            "date_str": date_str,
            "date_source": source_tag,
            "confidence": confidence,
            "target_dir": target_subfolder,
            "parsed_dt": parsed_dt,
            "is_photo": is_photo
        }
