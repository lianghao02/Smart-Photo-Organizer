import sys
import os

# 確保專案根目錄在 sys.path 中，以便單元測試匯入專案主模組
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
