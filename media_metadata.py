# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 媒體 Metadata 解析與日期/異常隔離決策模組 (v4.2 精準 7 分截圖引擎與共用設定版)
包含符合 ACID 的 Sidecar JSON 原子落碟 (write_sidecar_atomic) 與完整 7 分截圖/監視器畫面過濾 (calculate_screenshot_score)。
"""

import os
import re
import json
import datetime
from typing import Optional, Dict, Any, Tuple, List


def write_sidecar_atomic(sidecar_bytes: bytes, target_json_path: str) -> Tuple[bool, Optional[str]]:
    """
    Sidecar JSON 原子落碟寫入 helper:
    1. 寫入 <target_json_path>.part
    2. flush() 並呼叫 os.fsync() 強制落碟
    3. 執行 os.rename() / 'xb' 原子排他更名
    4. 發生 FileExistsError 或 OSError 時刪除 .part 檔並回傳 (False, error_msg)
    """
    if not sidecar_bytes or not target_json_path:
        return False, "Sidecar 位元組或目標路徑為空"

    json_part = target_json_path + ".part"
    try:
        with open(json_part, 'xb') as jf:
            jf.write(sidecar_bytes)
            jf.flush()
            os.fsync(jf.fileno())
        os.rename(json_part, target_json_path)
        return True, None
    except (FileExistsError, OSError) as e:
        if os.path.exists(json_part):
            try: os.remove(json_part)
            except OSError: pass
        return False, str(e)


class MediaMetadataExtractor:
    # 共用照片副檔名集合 (包含所有相機原生與 RAW 格式)
    EXT_PHOTOS = {
        '.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.bmp', '.tiff', '.raw', '.arw', '.cr2', '.nef',
        '.cr3', '.dng', '.orf', '.rw2', '.pef', '.sr2'
    }

    # 精準常見螢幕解析度集合
    COMMON_SCREEN_SIZES = {
        (1280, 720), (1366, 768), (1600, 900), (1920, 1080),
        (2560, 1440), (3840, 2160), (720, 1280), (1080, 1920),
        (1080, 2340), (1080, 2400), (1170, 2532), (1440, 2560),
        (2400, 1080), (2532, 1170), (2340, 1080)
    }

    # 低可信度日期門檻 (與主 Processor 保持一致)
    DATE_LOW_CONFIDENCE_THRESHOLD = 50

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
    def calculate_screenshot_score(cls, part_path: str, original_filename: str) -> Tuple[int, List[str]]:
        """
        完整 7 分制截圖／監視器畫面評分引擎 (與 ImageOps 評分規則完全相符)
        使用原始檔名、關鍵字、副檔名、.part 實體圖片尺寸、SubIFD 與相機 EXIF 特徵綜合評估。
        """
        fn_lower = original_filename.lower()
        ext = os.path.splitext(fn_lower)[1]
        score = 0
        reasons: List[str] = []

        # 1. 檔名與監視器頻道關鍵字評分 (注：LINE 相簿 line_album_ 不記 7 分)
        if any(kw in fn_lower for kw in ('screenshot', 'screen_shot', '螢幕快照', '螢幕截圖', '截圖')):
            score += 7
            reasons.append("截圖檔名(+7)")
        if any(kw in fn_lower for kw in ('surveillance', 'cctv', '監視器')):
            score += 7
            reasons.append("監視器檔名(+7)")
        if re.search(r'(?:^|[-_ ])(?:cam|ch|channel)[-_ ]?\d{1,3}(?:[-_ .]|$)', fn_lower):
            score += 7
            reasons.append("監視器頻道編號(+7)")

        if ext in ('.png', '.webp'):
            score += 1
            reasons.append("常見截圖格式(+1)")

        # 2. .part 實體圖片尺寸、常見螢幕解析度與相機 EXIF SubIFD 評分
        width = height = 0
        has_camera_exif = False
        metadata_checked = False

        if os.path.exists(part_path):
            try:
                from PIL import Image
                with Image.open(part_path) as img:
                    width, height = img.size
                    metadata_checked = True
                    exif = img.getexif() if hasattr(img, 'getexif') else None
                    camera_tags = {271, 272, 33434, 33437, 34855, 36867, 37377, 37378}
                    has_camera_exif = any(tag in exif for tag in camera_tags) if exif else False
                    
                    if exif and 34665 in exif:
                        try:
                            sub_ifd = exif.get_ifd(34665)
                            has_camera_exif = has_camera_exif or any(tag in sub_ifd for tag in camera_tags)
                        except Exception:
                            pass
            except Exception:
                pass

        if metadata_checked:
            if has_camera_exif:
                score -= 5
                reasons.append("具有相機 EXIF(-5)")
            else:
                score += 2
                reasons.append("缺少相機 EXIF(+2)")

        if width > 0 and height > 0:
            if (width, height) in cls.COMMON_SCREEN_SIZES or (height, width) in cls.COMMON_SCREEN_SIZES:
                score += 2
                reasons.append("常見螢幕尺寸(+2)")
            if height > width and (height / float(width)) >= 1.6 and width <= 1440:
                score += 3
                reasons.append("手機直向螢幕比例(+3)")
            elif width > height and (width / float(height)) >= 1.6 and height <= 1440:
                score += 3
                reasons.append("手機橫向螢幕比例(+3)")

        return max(0, score), reasons

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
        smart_screenshot: bool = True,
        low_confidence_threshold: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        針對 .part 暫存檔解析 EXIF/ffprobe Metadata，整合 Sidecar JSON 呼叫 DateParser 進行日期決策
        並依據 7 分截圖、DateConflict 與 LowConfidenceDate 進行階層式異常隔離。
        """
        orig_ext = os.path.splitext(filename)[1].lower()
        is_photo = orig_ext in cls.EXT_PHOTOS
        sub_type_folder = "Photos" if is_photo else "Videos"

        # 1. 執行 7 分制截圖識別過濾
        score, reasons = cls.calculate_screenshot_score(part_path, filename)
        is_screenshot = smart_screenshot and (score >= 7)

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

        threshold = low_confidence_threshold if low_confidence_threshold is not None else cls.DATE_LOW_CONFIDENCE_THRESHOLD

        # 4. Phase 4 階層式異常隔離路徑計算 (Screenshots ➔ DateConflict ➔ LowConfidenceDate ➔ Standard)
        if is_screenshot:
            target_subfolder = os.path.join(dst_root, "_Excluded", "Screenshots")
        elif has_conflict:
            target_subfolder = os.path.join(dst_root, "_Review", "DateConflict", year_str, sub_type_folder)
        elif confidence < threshold:
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
            "is_screenshot": is_screenshot,
            "screenshot_score": score,
            "screenshot_reasons": reasons
        }
