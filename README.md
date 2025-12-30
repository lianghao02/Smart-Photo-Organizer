# Smart Photo Organizer (Pro)

這是一個專為整理大量混亂照片/影片備份設計的自動化工具，特別針對 Google Takeout 下載的資料、原況照片 (Live Photos) 以及各種日期混亂的舊檔案進行了優化。

## ✨ 核心功能

### 🛡️ 智慧分類與隔離

- **日期分類**：自動依據 `YYYY-MM` 將照片分至不同月份資料夾。
- **截圖隔離**：自動識別檔名含 "Screenshot", "截圖" 等字樣，移至 `_Screenshots`。
- **重複隔離**：內建 MD5 內容比對，重複的檔案會移至 `_Duplicates` 並標註原始檔。
- **無日期處理**：完全找不到拍攝時間的檔案，會移至 `No_Date` 並保留原名。
- **Live Photos 支援**：自動偵測原況照片 (HEIC+MOV)，將其成對歸類至 `_LivePhotos` 並強制保留原名以維持播放功能。

### 📅 強大的日期解析 (Priority)

程式依序掃描以下資訊來決定拍攝日期：

1. **JSON Sidecar**：Google Takeout 產生的 `.json` 檔。
2. **SubIFD Exif**：優先讀取相機原始拍攝時間 (解決軟體修改日期覆蓋問題)。
3. **Standard Exif**：標準 EXIF 日期。
4. **Filename Regex**：解析檔名中的日期 (如 `VID20210310...`)。

## 🚀 快速開始

### 1. 安裝依賴

本專案依賴 `Pillow` 與 `pillow-heif` 來處理圖片與 HEIC 格式。

```bash
pip install Pillow pillow-heif
```

### 2. 執行程式

```bash
python photo_organizer.py
```

### 3. 操作介面

- **來源/目標資料夾**：選擇您的照片來源與整理後存放的位置。
- **模式選擇**：
  - **複製 (預設)**：最安全，保留原始檔案。
  - **移動**：整理後會移動檔案，可勾選刪除空資料夾。
- **重命名選項**：可勾選是否將檔案重命名為 `YYYY_MM_DD_流水號` (Live Photos 除外)。

## 📝 版本資訊

- **v2.9**: 最終交付版，包含所有修復與功能增強。
