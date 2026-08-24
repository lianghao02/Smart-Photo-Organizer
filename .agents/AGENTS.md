# Codex 專案指引

先讀取根目錄 `AGENTS.md`、`docs/tasks.md`、`docs/spec.md` 與 `docs/DEVELOPMENT_RULES.md`。

- 負責程式碼審查、邊界條件、回歸測試與必要的小範圍修正。
- 不修改 `.gemini/`；不複製或同步 Antigravity 指引。
- 以 `scripts/qa.ps1` 驗證實際結果，並以 Git 差異做審查依據。
- 使用 `codex/dev` Worktree；不得與 Antigravity 共用工作資料夾。
