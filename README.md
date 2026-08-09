# 智慧照片整理助手 Smart-Photo-Organizer v3.0

Smart-Photo-Organizer 是 Windows 本機照片清理與日期歸檔工具，支援一般資料夾、外接硬碟，以及已下載至本機的 Google Takeout ZIP。

v3.0 採「先分析、人工審核、最後處理」流程。按下「開始分析」只會建立索引、SQLite 狀態、報表與 Windows 捷徑，不會搬移、刪除或改名來源媒體；原始 Takeout ZIP 永遠唯讀。

## 核心安全規則

- `_Review/01`～`06` 只包含 `.lnk` 捷徑，刪除或移動這些捷徑不影響原始檔。
- 只有放入 `_Review/99_待刪除` 的已登記捷徑，才可在預覽與確認後觸發 MediaGroup 隔離。
- 媒體、Google JSON Sidecar、Live Photo 與 RAW/JPEG 配對檔一律整組處理。
- 待刪除群組只移至 `_Quarantine/待刪除`；程式不提供永久刪除。
- 正式搬移採零覆寫命名、SHA-256 驗證與 SQLite 續傳狀態。

## 使用流程

1. 選擇「一般資料夾」或「Takeout ZIP」，再選擇整理工作與歸檔位置。
2. 按「開始分析」。系統按需讀取媒體並建立下列審核捷徑：

   - `01_重複照片`
   - `02_相似照片`
   - `03_模糊照片`
   - `04_螢幕截圖`
   - `05_短影片`
   - `06_日期異常`

3. 按「開啟審核資料夾」人工檢查；把確定要排除的捷徑移到 `99_待刪除`。
4. 按「處理待刪除」。程式先顯示 DRY_RUN 摘要，確認後才整組移至 Quarantine。
5. 按「依日期整理」。日期可靠且未列入待刪除的 MediaGroup 會歸檔至 `YYYY/MM/Photos` 或 `YYYY/MM/Videos`。

## 分析規則摘要

- 完全重複：整個 MediaGroup 的非 JSON 成員須具備相同容量與完整雜湊。
- 相似照片：先依拍攝時間、方向與長寬比分桶，再使用 dHash 分段索引，不執行全庫 O(n²) 比較。
- 模糊照片：OpenCV Laplacian 僅列為人工候選；未安裝 OpenCV 時會略過並記錄警告。
- 螢幕截圖／監視器畫面：沿用可解釋 7 分制，達門檻才列入審核。
- 短影片：長度小於或等於 5 秒列入審核；Live Photo 配對影片會在探測秒數前排除。
- 日期異常：高可信來源衝突、缺少日期或可信度低於 50 分時列入審核並更新 `date_audit.csv`。

## Google Takeout ZIP

- 不需事先全量解壓。
- ZIP 中央目錄先通過路徑穿越、Symlink、加密成員、壓縮比與容量上限檢查。
- 一次只串流解壓目前 MediaGroup；未命中審核分類的快取會立即清理。
- 命中審核分類的群組才保留在 `_ReviewCache/<job_id>/<group_id>`，供 Windows 捷徑檢視。
- 支援跨 ZIP Sidecar、`照片.jpg.json`、`照片.json`、重複編號與 `supplemental-metadata.json` 已知變體。

## 執行環境

- Windows 10／11
- Python 3.12
- 安裝依賴：`pip install -r requirements.txt`
- 建議安裝 FFmpeg，或以 `FFPROBE_PATH` 指定 `ffprobe.exe`，供影片日期與長度解析。

可直接執行 `start_organizer.bat`，或執行：

```powershell
python main.py
```

## 驗證

```powershell
python -m py_compile *.py
python -m unittest discover -v
```

v3.0 最終驗收共執行 137 項測試：136 項通過，1 項 Symlink 測試因目前 Windows 權限不足而明確略過，無失敗項目。
