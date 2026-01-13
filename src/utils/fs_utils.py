# -*- coding: utf-8 -*-
import os
import re

class FSUtils:
    
    @staticmethod
    def get_unique_path(path: str, reserved_paths: set = None) -> str:
        """
        Returns a unique file path.
        If path exists OR is in reserved_paths (for dry run), appends _1, _2, etc.
        """
        def is_taken(p):
            if os.path.exists(p): return True
            if reserved_paths is not None and p in reserved_paths: return True
            return False

        if not is_taken(path):
            return path
            
        base, ext = os.path.splitext(path)
        counter = 1
        new_path = f"{base}_{counter}{ext}"
        while is_taken(new_path):
            counter += 1
            new_path = f"{base}_{counter}{ext}"
        return new_path

    @staticmethod
    def remove_empty_folders(path: str):
        """
        Recursively remove empty folders.
        """
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
    def get_sequence_name(target_dir: str, prefix: str, ext: str, dir_counters: dict, reserved_paths: set = None) -> str:
        """
        Generates YYYY_MM_DD_001.ext, utilizing a cache `dir_counters`
        to avoid repeatedly scanning the directory.
        Checks both file system and reserved_paths for collisions.
        dir_counters key format: (target_dir, prefix)
        """
        key = (target_dir, prefix)
        
        # 1. Initialize counter if not present
        if key not in dir_counters:
            max_seq = 0
            if os.path.exists(target_dir):
                # Scan explicitly for this pattern
                try:
                    # Pattern: prefix_(\d+).ext
                    pattern = re.compile(re.escape(prefix) + r'_(\d+)')
                    
                    for fname in os.listdir(target_dir):
                        if fname.startswith(prefix + "_"):
                            base_name = os.path.splitext(fname)[0]
                            match = pattern.fullmatch(base_name)
                            if match:
                                try:
                                    num = int(match.group(1))
                                    if num > max_seq:
                                        max_seq = num
                                except:
                                    pass
                except Exception:
                    pass
            dir_counters[key] = max_seq

        # 2. Increment and check
        current_seq = dir_counters[key] + 1
        dir_counters[key] = current_seq
        
        # 3. Double check existence
        while True:
            new_name = f"{prefix}_{current_seq:03d}{ext}"
            new_path = os.path.join(target_dir, new_name)
            
            is_taken = False
            if os.path.exists(new_path): is_taken = True
            if reserved_paths is not None and new_path in reserved_paths: is_taken = True
            
            if not is_taken:
                return new_path
            
            # Collision found (rare or dry run), try next
            current_seq += 1
            dir_counters[key] = current_seq
