# 開發與雙 Agent 協作規則

本專案沿用 `00_home/docs/DEVELOPMENT_RULES.md` 的共用契約；本檔記錄 Smart Photo Organizer 的實際入口。

## 驗證

```powershell
.\scripts\qa.ps1
```

此命令會依序執行 `unittest`、敏感字串掃描與 Git 差異檢查。GitHub Actions 只執行相同的跨平台測試；Windows GUI、`pywebview` 視窗、捷徑及實際 Google Takeout 資料必須由本機人工驗收。

## Agent 邊界

- Codex 讀取 `.agents/AGENTS.md`，負責審查、測試、邊界條件與小範圍修正。
- Antigravity 讀取 `.gemini/AGENTS.md`，負責任務實作與跨檔案整合。
- 兩者共用本目錄的程式、測試、文件、GitHub Actions 和 `scripts/`；不得共用未提交工作區、虛擬環境或 Agent 暫存資料。

## Worktree

在 `00_home` 執行：

```powershell
.\scripts\New-AgentWorktree.ps1 -Project Smart-Photo-Organizer -Agent both
```

會建立 `10_Smart-Photo-Organizer-codex`（`codex/dev`）與 `10_Smart-Photo-Organizer-ag`（`ag/dev`）。首次使用可先加 `-WhatIf` 預覽。
