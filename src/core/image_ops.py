# -*- coding: utf-8 -*-
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
except ImportError:
    Nominatim = None

try:
    import reverse_geocoder as rg
except ImportError:
    rg = None

try:
    from PIL import Image
except ImportError:
    Image = None

class ImageOps:
    _geolocator = None
    _geo_cache = {} # {(lat_rounded, lon_rounded): "Country_City"}
    
    @staticmethod
    def _init_geolocator():
        if ImageOps._geolocator is None and Nominatim:
            # User agent is required by Nominatim
            ImageOps._geolocator = Nominatim(user_agent="smart_photo_organizer_v2", timeout=3)

    @staticmethod
    def is_blurry(path: str, threshold: float = 100.0) -> (bool, float):
        """
        Returns (is_blurry, score) using Laplacian Variance.
        """
        if cv2 is None:
            return False, 0.0
            
        try:
            # OpenCV doesn't natively support non-ascii paths on Windows, use fromfile -> imdecode
            img_array = np.fromfile(path, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
            
            if img is None: return False, 0.0

            score = cv2.Laplacian(img, cv2.CV_64F).var()
            return score < threshold, score
        except:
            return False, 0.0

    @staticmethod
    def get_location_folder(path: str) -> str:
        """
        Returns "Country_City" (Chinese preferred) or None.
        Tries Online (Nominatim) -> Offline (reverse_geocoder).
        """
        if not Image: return None
        
        lat_lon = ImageOps._get_lat_lon(path)
        if not lat_lon: return None
        
        lat, lon = lat_lon
        
        # 1. Try Online Cache / Request (Chinese)
        if Nominatim:
            ImageOps._init_geolocator()
            if ImageOps._geolocator:
                # Round to 3 decimals (~100m) to increase cache hits
                cache_key = (round(lat, 3), round(lon, 3))
                
                if cache_key in ImageOps._geo_cache:
                    return ImageOps._geo_cache[cache_key]
                
                try:
                    location = ImageOps._geolocator.reverse((lat, lon), language='zh-TW', exactly_one=True)
                    if location:
                        address = location.raw.get('address', {})
                        country = address.get('country', '')
                        # Hierarchy for City: city -> county -> town -> suburb
                        city = address.get('city', address.get('county', address.get('town', address.get('suburb', ''))))
                        
                        if not country: country = "未知國家"
                        if not city: city = "未知城市"
                        
                        final_loc = f"{country}_{city}"
                        # Save to cache
                        ImageOps._geo_cache[cache_key] = final_loc
                        return final_loc
                except (GeocoderTimedOut, GeocoderServiceError, Exception):
                    # Fallback to offline if timeout or error
                    pass

        # 2. Offline Fallback (reverse_geocoder)
        if rg:
            try:
                # reverse_geocoder takes [(lat, lon)]
                results = rg.search([lat_lon], mode=2) 
                if results:
                    data = results[0]
                    country = data.get('cc', 'Unknown')
                    city = data.get('name', 'Unknown')
                    
                    safe_country = "".join([c for c in country if c.isalnum() or c in (' ', '_')]).strip()
                    safe_city = "".join([c for c in city if c.isalnum() or c in (' ', '_')]).strip()
                    
                    if not safe_country: safe_country = "Unknown"
                    if not safe_city: safe_city = "Location"
                    
                    return f"{safe_country}_{safe_city}"
            except Exception:
                pass
                
        return None

    @staticmethod
    def _get_lat_lon(path):
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                if not exif: return None
                
                # GPS Info Tag ID = 34853
                gps_info = exif.get_ifd(34853)
                if not gps_info: return None
                
                gps_lat_ref = gps_info.get(1)
                gps_lat = gps_info.get(2)
                gps_lon_ref = gps_info.get(3)
                gps_lon = gps_info.get(4)
                
                if gps_lat and gps_lat_ref and gps_lon and gps_lon_ref:
                    lat = ImageOps._convert_to_degrees(gps_lat)
                    lon = ImageOps._convert_to_degrees(gps_lon)
                    
                    if gps_lat_ref != "N": lat = -lat
                    if gps_lon_ref != "E": lon = -lon
                    return (lat, lon)
        except:
            pass
        return None

    @staticmethod
    def _convert_to_degrees(value):
        try:
            d = value[0]
            m = value[1]
            s = value[2]
            return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)
        except:
            return 0.0
