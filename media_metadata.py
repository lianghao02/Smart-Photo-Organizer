# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 媒體 Metadata 解析與日期決策模組 (v3.0 Phase 3 版)
讀取 .part 暫存檔之 EXIF、ffprobe 與 Sidecar JSON，呼叫 DateParser 決策最佳年份/月份與歸檔路徑。
"""

import os
import json
import datetime
from typing import Optional, Dict, Any, Tuple

# 引入專案日期解析器
import main as app_main


class MediaMetadataExtractor:
    @staticmethod
    def parse_sidecar_json_bytes(json_bytes: bytes) -> Optional[dict]:
        """從 Sidecar JSON 位元組解析 photoTakenTime 或 creationTime 數據"""
        if not json_bytes:
            return None
        try:
            data = json.loads(json_bytes.decode('utf-8', errors='ignore'))
            # 優先讀取 photoTakenTime
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
        json_data: Optional[dict] = None,
        folder_pattern: str = "ym",
        rename_mode: str = "date_seq"
    ) -> Dict[str, Any]:
        """
        針對 .part 暫存檔解析 EXIF/ffprobe Metadata，整合 Sidecar JSON 呼叫 DateParser 進行 8 階層日期決策
        回傳最佳日期候選、置信度與目標資料夾/檔案候選名稱
        """
        # 使用專案標準 DateParser
        dp = app_main.DateParser()
        
        # 1. 如果有 Sidecar JSON 數據，將 Unix timestamp 轉為 ISO 字串供 DateParser 使用
        google_json_date = None
        if json_data and 'timestamp' in json_data:
            try:
                dt = datetime.datetime.fromtimestamp(json_data['timestamp'], datetime.timezone.utc)
                google_json_date = dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pass

        # 2. 解析 .part 實體檔之 EXIF 與多媒體日期
        file_date_info = dp.get_file_dates(part_path, google_json_date=google_json_date)

        # 3. 執行 8 階層日期決策
        parsed_dt, source_tag, confidence = dp.parse_date_with_confidence(filename, file_date_info)

        if parsed_dt:
            date_str = parsed_dt.strftime('%Y-%m-%d')
            year_str = parsed_dt.strftime('%Y')
            month_str = parsed_dt.strftime('%Y-%m')
        else:
            date_str = None
            year_str = "No_Date"
            month_str = "No_Date"

        # 4. 根據 folder_pattern 計算目標歸檔資料夾路徑
        if folder_pattern == "y":
            target_subfolder = os.path.join(dst_root, year_str)
        elif folder_pattern == "ym":
            target_subfolder = os.path.join(dst_root, year_str, month_str)
        else:
            target_subfolder = os.path.join(dst_root, year_str, month_str)

        if not parsed_dt:
            target_subfolder = os.path.join(dst_root, "No_Date")

        return {
            "date_str": date_str,
            "date_source": source_tag,
            "confidence": confidence,
            "target_dir": target_subfolder,
            "parsed_dt": parsed_dt
        }
