# 🗂️ 智慧照片整理助手 (Smart Photo Organizer) v2.9 (Pro Web)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Version](https://img.shields.io/badge/版本-v2.9-green)
![UI](https://img.shields.io/badge/UI-PyWebView%20HTML5-blue)

專為整理大量混亂的照片與影片備份而設計，特別針對 **Google Takeout** 匯出資料、**原況照片 (Live Photos)** 以及日期混亂的舊檔進行最佳化。提供現代化深色 Glassmorphism HTML5 介面 (PyWebView + 本機 HTTP Server)，支援多執行緒並行處理。

---

## 🚀 快速開始

### 1. 安裝依賴

```bash
# 必要套件 (含 Web UI)
pip install pywebview Pillow pillow-heif

# 選用功能（GPS 地點解析）
pip install geopy reverse_geocoder

# 選用功能（模糊照片偵測）
pip install opencv-python numpy

# 選用功能（更快的雜湊演算）
pip install xxhash
```

### 2. 執行程式

在檔案總管中直接雙擊 **`start_organizer.bat`**，或在終端機執行：

```bash
python main.py
```

### 3. 操作流程

1. 選擇**來源資料夾**（含照片的目錄）
2. 選擇**目標資料夾**（整理後存放的位置；若留空自動進行「原地歸檔」）
3. 設定整理選項（模式、重命名格式、資料夾分類結構等）
4. 點擊「▶ 開始整理」

---

## ✨ v2.9 最新特色

| 功能 | 說明 |
| --- | --- |
| **全 Web 現代化 UI** | 採用內建 PyWebView HTTP Server 託管 HTML5/CSS 介面，100% 避免 `file://` 跨域限制 |
| **雙重重新命名模式** | 支援 **📅 拍攝日期+流水號** (`2024_05_20_001.jpg`) 與 **🔢 純流水號** (`001.jpg`) |
| **智慧檔名防碰撞** | 重構檔名衝突演算法，自動識別並歸併重複 `_1_1` 尾綴為俐落的 `_1`, `_2`, `_3` |
| **全雲端空間防下載** | 同時支援 Windows **OneDrive** 與 **Google Drive** 電腦版，隨選檔案 100% 不觸發強制下載 |
| **隔離資料夾標籤化** | 特殊資料夾中的檔案帶有明確前綴，如重複照片 (`DUP_2024_05_20_001.jpg`) / 截圖 (`Shot_`) / 模糊 (`Blur_`) |
| **自訂分類層級** | 支援「年/月 (`2024/05`)」、「年/月-日 (`2024/05-20`)」與「僅年份 (`2024`)」三種結構 |
| **一鍵檢視成果** | 任務完成後可點擊 **[📂 開啟目標資料夾]** 按鈕直接喚起 Windows 檔案總管 |
| **極簡雙模式** | 簡化為 **📄 複製 (Copy)** 與 **📦 移動 (Move / 原地與跨區歸檔)** 兩大核心模式 |
| **預設安全防禦** | 全域預設啟用 **重複照片內容去重** 與 **斷點續傳歷史資料庫** (`history_log.json`) |

---

## 🛠️ 技術棧

| 分類 | 使用技術 |
| --- | --- |
| **GUI 介面** | PyWebView + Vanilla HTML5/CSS (Dark Glassmorphism) + JS Queue 輪詢 |
| **影像處理** | Pillow + pillow-heif |
| **GPS 解析** | geopy (Nominatim) + reverse_geocoder (離線備援) |
| **模糊偵測** | OpenCV (Laplacian Variance) |
| **雜湊演算** | xxhash (優先) / hashlib MD5 (備援) |
| **架構** | 集中式 Python 模組 + 獨立 index.html，不硬編碼本機絕對路徑 |

---

## 📄 授權

[MIT License](LICENSE)

