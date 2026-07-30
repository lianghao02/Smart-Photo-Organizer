# 📸 智慧相片自動分類助手 Smart-Photo-Organizer (v2.9 Pro Web)

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