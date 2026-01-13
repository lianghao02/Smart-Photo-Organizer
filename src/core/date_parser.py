# -*- coding: utf-8 -*-
import os
import datetime
import json
import re
from typing import Optional
from src.utils.logger import Logger

# Try importing Pillow
try:
    from PIL import Image, ExifTags
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    Image = None

class DateParser:
    def __init__(self):
        self.logger = Logger.get_instance()

    def get_date(self, path: str, is_photo: bool) -> Optional[datetime.datetime]:
        # 1. JSON Sidecar
        try:
            json_path = path + ".json"
            if os.path.exists(json_path):
                date = self._parse_json_date(json_path)
                if date and self._is_valid_date(date, f"JSON: {os.path.basename(json_path)}"): return date
            
            base_name = os.path.splitext(path)[0]
            json_path_2 = base_name + ".json"
            if os.path.exists(json_path_2):
                 date = self._parse_json_date(json_path_2)
                 if date and self._is_valid_date(date, f"JSON: {os.path.basename(json_path_2)}"): return date
        except Exception:
            pass

        # 2. Image EXIF
        if is_photo and Image:
            exif_date = self._get_exif_date(path)
            if exif_date: return exif_date
        
        # 3. Filename Regex
        filename = os.path.basename(path)
        date_from_name = self._parse_filename_date(filename)
        if date_from_name and self._is_valid_date(date_from_name, "Filename"):
            return date_from_name

        # 4. Sibling Image Check (For Video/Live Photos)
        if not is_photo:
            base_path = os.path.splitext(path)[0]
            for img_ext in ['.heic', '.HEIC', '.jpg', '.JPG', '.jpeg', '.JPEG']:
                sibling_path = base_path + img_ext
                if sibling_path != path and os.path.exists(sibling_path):
                    # Recursive call treating sibling as photo
                    sib_date = self.get_date(sibling_path, is_photo=True)
                    if sib_date: return sib_date

        return None

    def _get_exif_date(self, path) -> Optional[datetime.datetime]:
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                if not exif: return None

                # 1. Check SubIFD (0x8769 / 34665)
                if 34665 in exif:
                    try:
                        sub_exif = exif.get_ifd(34665)
                        # DateTimeOriginal (36867)
                        d = self._try_parse_exif(sub_exif.get(36867))
                        if d and self._is_valid_date(d, "Exif-Original"): return d
                        
                        # DateTimeDigitized (36868)
                        d = self._try_parse_exif(sub_exif.get(36868))
                        if d and self._is_valid_date(d, "Exif-Digitized"): return d
                        
                        # DateTime (306)
                        d = self._try_parse_exif(sub_exif.get(306))
                        if d and self._is_valid_date(d, "Exif-SubIFD"): return d
                    except:
                        pass

                # 2. Check IFD0 (Standard Tags)
                # DateTimeOriginal
                d = self._try_parse_exif(exif.get(36867))
                if d and self._is_valid_date(d, "Exif-IFD0"): return d
                
                # DateTime
                d = self._try_parse_exif(exif.get(306))
                if d and self._is_valid_date(d, "Exif-IFD0-DT"): return d
                
        except Exception:
            pass
        return None

    def _try_parse_exif(self, dt_str) -> Optional[datetime.datetime]:
        if not dt_str: return None
        try:
            return datetime.datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
        except:
            return None

    def _parse_json_date(self, json_path) -> Optional[datetime.datetime]:
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                taken = data.get('photoTakenTime', {})
                ts = taken.get('timestamp')
                if ts:
                    return datetime.datetime.fromtimestamp(int(ts))
        except:
            pass
        return None

    def _parse_filename_date(self, filename) -> Optional[datetime.datetime]:
        # YYYYMMDD
        match = re.search(r'(20\d{2}|19\d{2})[-_]?(\d{2})[-_]?(\d{2})', filename)
        if match:
            try:
                y, m, d = match.groups()
                return datetime.datetime(int(y), int(m), int(d))
            except:
                pass
        
        # Timestamp (13 digits)
        match_ts = re.search(r'(\d{13})', filename)
        if match_ts:
            try:
                ts = int(match_ts.group(1)) / 1000
                return datetime.datetime.fromtimestamp(ts)
            except:
                pass
        return None

    def _is_valid_date(self, date_obj, src_info="") -> bool:
        if not date_obj: return False
        if date_obj.year < 1900: return False
        
        now = datetime.datetime.now()
        max_date = now + datetime.timedelta(days=30)
        
        if date_obj > max_date:
            self.logger.warn(f"日期異常(未來): {date_obj} ({src_info}) -> 將歸類至 No_Date")
            return False
        return True
