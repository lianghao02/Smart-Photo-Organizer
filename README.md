# 🗂️ 智慧照片整理助手 (Smart Photo Organizer) v2.8

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Version](https://img.shields.io/badge/版本-v2.8-green)
![Architecture](https://img.shields.io/badge/架構-單一檔案-blue)

專為整理大量混亂的照片與影片備份而設計，特別針對 **Google Takeout** 匯出資料、**原況照片 (Live Photos)** 以及日期混亂的舊檔進行最佳化。提供全功能 tkinter GUI 介面，支援多執行緒並行處理。

---

## 🚀 快速開始

### 1. 安裝依賴

```bash
# 必要套件
pip install Pillow pillow-heif

# 選用功能（GPS 分類）
pip install geopy

# 選用功能（模糊偵測）
pip install opencv-python numpy

# 選用功能（更快的雜湊演算）
pip install xxhash
```

### 2. 執行程式

```bash
python main.py
```

或直接雙擊 **`start_organizer.bat`**。

### 3. 操作流程

1. 選擇**來源資料夾**（含照片的目錄）
2. 選擇**目標資料夾**（整理後存放的位置）
3. 設定整理選項（模式、重命名、GPS 等）
4. 點擊「▶ 開始整理」

---

## ✨ 功能特色

| 功能 | 說明 |
| --- | --- |
| **格式支援** | JPG, PNG, HEIC, RAW (NEF, CR2, DNG 等), 影片 MP4/MOV 等十多種格式 |
| **智慧日期解析** | JSON Sidecar → EXIF SubIFD → 標準 EXIF → 檔名 Regex，優先順序自動判斷 |
| **強制序號命名** | 支援完全按拍攝時間先後順序，強制將檔案重新命名為 `001.jpg` 的純序號格式 |
| **截圖隔離** | 自動偵測截圖關鍵字與相機長寬比，嚴格模式支援手機直向截圖過濾 |
| **重複去除** | 三段式雜湊（檔頭+中段+尾端）精準比對，效能極高 |
| **Live Photos** | 自動偵測 HEIC+MOV 配對，保留原始檔名並移至 `_LivePhotos` |
| **GPS 地點分類** | 自動解析座標，建立「台灣_台北市」風格的子資料夾 |
| **OneDrive 防護** | 專為 Windows OneDrive 設計，辨識線上與同步中檔案，不觸發全盤下載 |
| **模糊偵測** | Laplacian 方差演算法偵測模糊照片，移至 `_Blurry` |
| **斷點續傳** | `history_log.json` 記錄進度，重啟後自動跳過已處理檔案 |
| **預覽模式** | 模擬所有操作，產出 `preview_report.csv`，不寫入硬碟 |

---

## 🛠️ 技術棧

| 分類 | 使用技術 |
| --- | --- |
| **GUI** | Python tkinter + ttk (clam 主題) |
| **影像處理** | Pillow + pillow-heif |
| **GPS 解析** | geopy (Nominatim) + reverse_geocoder (離線備援) |
| **模糊偵測** | OpenCV (Laplacian Variance) |
| **雜湊演算** | xxhash (優先) / hashlib MD5 (備援) |
| **架構** | 單一 `main.py` 交付，9 個模組合併，無外部路徑依賴 |

---

## 📄 授權

[MIT License](LICENSE)
