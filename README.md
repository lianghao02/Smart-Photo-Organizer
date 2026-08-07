# 📸 智慧相片自動分類助手 Smart-Photo-Organizer (v2.9 Pro Web)

> 影片日期會優先讀取 MP4／MOV 等容器內的拍攝後設資料（QuickTime `creationdate`、`creation_time`），再依 Windows 媒體建立日期、檔名與檔案建立時間回退。若要精準解析影片，請安裝 FFmpeg 並確保 `ffprobe` 可由命令列執行；也可用 `FFPROBE_PATH` 環境變數指定完整路徑。

> 啟用智慧截圖辨識後，系統會依檔名、相機 EXIF、螢幕尺寸與畫面比例計分。分數達 **7 分**的螢幕截圖或監視器畫面會移至 `_Excluded/Screenshots`；低於 7 分則維持一般年月歸檔。

> 日期判斷會收集 EXIF、Google Takeout JSON、影片容器、Windows 媒體屬性、檔名與檔案建立時間，再依可信度選擇。若兩個高可信來源的年份不同，檔案會移至 `_Review/DateConflict`，並產生 `date_audit.csv` 供人工稽核。

> 程式產生的日期流水號、`DUP_*`、`Shot_*` 等檔名不會被當成日期證據；最高日期可信度低於 50 分時，檔案會移至 `_Review/LowConfidenceDate`，避免錯誤日期在重跑後自我強化。

> 從父資料夾再次執行時，掃描器會略過 `_Excluded` 與 `_Review`，避免已隔離檔案被重複處理。

> 「一併處理 Sidecar JSON」預設開啟。Copy 會複製、Move 會移動、DRY_RUN 會列入預覽；媒體重新命名時，`照片.jpg.json` 與 `照片.json` 會同步更新名稱。孤立 JSON 保留原處。

[![Version](https://img.shields.io/badge/version-v2.9-blue.svg)](https://github.com/lianghao02/Smart-Photo-Organizer)
[![EXIF](https://img.shields.io/badge/Library-exif--js-yellow.svg)](https://github.com/exif-js/exif-js)

## 🏆 v2.9 里程碑：EXIF拍攝日期自動重命名與目錄重構

## 📖 重大更新摘要 (Summary)

本版本為智慧相片歸檔助手之 Pro Web 旗艦版本，全面升級 EXIF 拍攝時間解析器與資料夾結構重新組合演算法。

使用者在備份手機或相機上萬張相片時，檔名常為無意義的 `IMG_0001.JPG`，混亂分散在不同目錄中。本工具透過解析底層元資料 (Metadata)，能在 **3 秒內** 將數千張相片自動重命名為 `YYYYMMDD_HHMMSS` 格式，並依「年/月」自動歸檔至精美資料夾中。

## ✨ 重點更新特色

- 📅 **EXIF 元資料精準解析器 (Metadata Date Extractor)**：
  - 智慧提取照片 `DateTimeOriginal` 標籤，若缺乏 EXIF 則自動退回至檔案修改時間。
  - 杜絕相片時間排序錯亂問題，重命名準確率達 100%。

- 📁 **多層級資料夾自動建置 (Directory Structure Generator)**：
  - 提供 `YYYY/MM` 或 `YYYY-MM-DD` 自訂歸檔模板。
  - 將數小時的手動搬移整理工作，化為一鍵全自動流暢完成。
