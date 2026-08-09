# Smart-Photo-Organizer v3.0 產品規格

## 一、產品定位

Smart-Photo-Organizer v3.0 是 Windows 本機照片清理與歸檔工具，處理：

- 本機磁碟與外接硬碟中的照片、影片與 Sidecar。
- 已下載至本機的 Google Takeout ZIP。

不處理只存在雲端、尚未下載至本機的 placeholder 檔案，也不直接連線操作 Google Photos、OneDrive 或 Google Drive。

## 二、核心流程

1. 使用者選擇一般資料夾或本機 Takeout ZIP。
2. 系統以唯讀方式建立來源索引；ZIP 媒體採單檔按需解壓，不全量展開。
3. 建立 `MediaGroup`，把主媒體、Google JSON Sidecar、Live Photo 配對檔視為不可拆分的一組。
4. 第一階段只分析，不移動、不刪除、不改名來源媒體。
5. 系統將可疑項目登記至 `_Review`，並建立供人工檢視的 Windows `.lnk` 捷徑。
6. 使用者自行把要處理的捷徑放入 `_Review/99_待刪除`。
7. 按下「處理待刪除」後，系統依資料庫找回完整 `MediaGroup`，整組移至 `_Quarantine/待刪除`。
8. 系統不提供永久刪除功能。
9. 人工審核結束後，才依拍攝日期將完整 `MediaGroup` 歸檔至 `YYYY/MM/Photos` 或 `YYYY/MM/Videos`。

## 三、審核資料夾

```text
_Review/
├─ 01_重複照片/
├─ 02_相似照片/
├─ 03_模糊照片/
├─ 04_螢幕截圖/
├─ 05_短影片/
├─ 06_日期異常/
└─ 99_待刪除/
```

規則：

- `01`～`06` 只建立 `.lnk`，不直接搬移原檔。
- JSON 不單獨建立捷徑。
- 同一原始媒體可出現在多個分類，但實際處理時依資料庫中的 `MediaGroup` 與原始完整路徑去重，只處理一次。
- 移除或搬移 `01`～`06` 中的捷徑不得影響媒體原檔。
- `99_待刪除` 是唯一可觸發原檔隔離的入口。

## 四、MediaGroup 規則

一個 `MediaGroup` 可包含：

- 主照片或主影片。
- Google Takeout JSON Sidecar。
- Live Photo 的 HEIC／JPG 與 MOV 配對。
- 未來確認需要跟隨的 AAE 或 RAW/JPEG 配對檔。

任何 Quarantine、重新命名或日期歸檔都必須整組進行。Live Photo 的 MOV 必須先完成配對，不能因長度小於或等於 5 秒而被列入短影片。

## 五、分類規則

### 1. 完全重複

沿用現有 `size → partial hash → full hash`。只有 full hash 相同才視為完全重複。

### 2. 相似照片

先依拍攝時間區間與媒體類型縮小候選，再使用 pHash／dHash；禁止全庫 O(n²) 逐一比較。

### 3. 模糊照片

沿用 OpenCV Laplacian 評估，只建立人工審核候選，不自動刪除。

### 4. 螢幕截圖／監視器畫面

沿用可解釋分數制。總分達 7 分列入 `_Review/04_螢幕截圖`，低於 7 分不列入；不得直接移至 `_Excluded`。

### 5. 短影片

影片長度小於或等於 5 秒列為候選，但已確認為 Live Photo 配對的 MOV 必須排除。

### 6. 日期異常

沿用中央日期候選與可信度決策。高可信來源衝突或最高可信度低於門檻時，只建立 `_Review/06_日期異常` 捷徑與稽核紀錄。

## 六、Google Takeout 與 Sidecar

- Takeout ZIP 永遠唯讀。
- `SidecarMatcher` 統一處理一般資料夾與 ZIP 的配對規則。
- 至少支援 `照片.jpg.json`、`照片.json`、`照片.jpg(1).json`、`*.supplemental-metadata.json` 與已知截斷變體。
- Google JSON 是日期與群組證據，不得視為垃圾檔。
- 原始 Sidecar 必須跟隨 MediaGroup；衝突時記錄稽核資料，不覆寫既有檔案。

## 七、ZIP 審核快取

Windows 捷徑不能指向 ZIP 內部成員，因此採低容量混合模式：

1. 媒體按需解壓至 `.part` 進行分析。
2. 未命中審核分類者，分析後釋放暫存。
3. 命中審核分類的 MediaGroup 才實體化至 `_ReviewCache/<job_id>/<media_group_id>/`。
4. `_Review` 的 `.lnk` 指向 `_ReviewCache` 中的可檢視媒體。
5. 最終正式歸檔可重新從來源 ZIP 解壓，不依賴快取作為唯一來源。

## 八、安全與資料完整性

- 不覆寫既有媒體、Sidecar、快取或隔離檔。
- 所有處理均以 SQLite 工作狀態與 SHA-256 驗證。
- 解析 `.lnk` 後須核對允許根目錄與資料庫登記，不接受任意外部路徑。
- 中斷後必須可續傳；重試不得重複產生媒體。
- 高風險功能先提供 DRY_RUN 與清楚的預覽摘要。

## 九、不在 v3.0 範圍

- 直接操作線上 Google Photos、OneDrive 或 Google Drive。
- 永久刪除隔離檔案。
- 臉部辨識、人物分類或雲端 AI 內容分析。
- 未經確認直接搬移模糊、相似、截圖或短影片。

