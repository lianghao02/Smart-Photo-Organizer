import hashlib
import os
try:
    import xxhash
    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False

from src.utils.config import ConfigConstants

class Dedup:
    @staticmethod
    def get_hash(path: str) -> str:
        """Calculate full file hash using xxHash (if available) or MD5."""
        if HAS_XXHASH:
            hasher = xxhash.xxh64()
        else:
            hasher = hashlib.md5()
            
        try:
            with open(path, 'rb') as f:
                while chunk := f.read(ConfigConstants.BLOCK_SIZE * 4): # Read bigger chunks
                    hasher.update(chunk)
            return hasher.hexdigest()
        except:
            return ""

    @staticmethod
    def get_partial_hash(path: str) -> str:
        """
        Calculate partial hash (Head + Middle + Tail) for fast comparison.
        Returns a string: 'SIZE_PARTIALHASH'
        """
        try:
            size = os.path.getsize(path)
            if size < 20480: # Small file (<20KB), just full hash
                return f"{size}_{Dedup.get_hash(path)}"
            
            if HAS_XXHASH:
                hasher = xxhash.xxh64()
            else:
                hasher = hashlib.md5()
                
            with open(path, 'rb') as f:
                # Head
                hasher.update(f.read(4096))
                
                # Middle
                f.seek(size // 2)
                hasher.update(f.read(4096))
                
                # Tail
                f.seek(-4096, 2)
                hasher.update(f.read(4096))
                
            return f"{size}_{hasher.hexdigest()}"
        except:
            return ""
