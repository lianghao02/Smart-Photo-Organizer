import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -*- coding: utf-8 -*-
"""v3.0 Phase 3 Review Workspace、ReviewEntry 與捷徑安全驗證。"""

import os
import shutil
import tempfile
import unittest

from import_state import TakeoutStateManager
from review_workspace import (
    PENDING_DELETE_DIRECTORY,
    REVIEW_CATEGORIES,
    ReviewWorkspaceError,
    ReviewWorkspaceManager,
)


class FakeShortcutBackend:
    """以文字檔模擬 `.lnk`，只用於跨平台測試產品控制流程。"""

    def create_shortcut(self, link_path: str, target_path: str) -> bool:
        os.makedirs(os.path.dirname(link_path), exist_ok=True)
        with open(link_path, "w", encoding="utf-8") as handle:
            handle.write(target_path)
        return True

    def resolve_shortcut(self, link_path: str):
        try:
            with open(link_path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return None


class TestReviewWorkspace(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.source_root = os.path.join(self.root, "來源照片")
        self.destination_root = os.path.join(self.root, "整理結果")
        os.makedirs(self.source_root)
        os.makedirs(self.destination_root)
        self.media_path = os.path.join(self.source_root, "測試照片.jpg")
        with open(self.media_path, "wb") as handle:
            handle.write(b"media")

        self.state = TakeoutStateManager(os.path.join(self.destination_root, "state.db"))
        self.job_id = "job_review_phase3"
        self.group_id = "mg_review_phase3"
        self.state.create_job(
            self.job_id,
            "IMPORT",
            self.source_root,
            self.destination_root,
        )
        self.state.create_media_group(
            group_id=self.group_id,
            job_id=self.job_id,
            primary_member_id=None,
            source_type="FOLDER",
            status="VALIDATED",
            members=[{
                "member_id": None,
                "source_key": "folder:測試照片.jpg",
                "role": "PRIMARY",
            }],
        )
        self.backend = FakeShortcutBackend()
        self.manager = ReviewWorkspaceManager(
            self.state,
            self.backend,
            self.destination_root,
            allowed_source_roots=[self.source_root],
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_initialize_creates_fixed_review_layout(self):
        """建立 01～06、99 與 ReviewCache，且不修改來源媒體。"""
        paths = self.manager.initialize()
        self.assertEqual(set(paths), set(REVIEW_CATEGORIES) | {"PENDING_DELETE"})
        self.assertTrue(all(os.path.isdir(path) for path in paths.values()))
        self.assertTrue(os.path.isdir(self.manager.cache_root))
        self.assertTrue(os.path.isfile(self.media_path))

    def test_register_review_creates_link_and_authoritative_db_entry(self):
        """捷徑與 SQLite ReviewEntry 同步建立，中文檔名可正常保留。"""
        entry = self.manager.register_review(
            self.job_id,
            self.group_id,
            "SCREENSHOT",
            self.media_path,
            score=8,
            reason="無相機 EXIF、符合常見螢幕比例",
        )

        self.assertEqual(entry.status, "READY")
        self.assertTrue(os.path.isfile(entry.shortcut_path))
        self.assertIn("測試照片.jpg", os.path.basename(entry.shortcut_path))
        record = self.state.get_review_entry(entry.review_entry_id)
        self.assertEqual(record["group_id"], self.group_id)
        self.assertEqual(record["category"], "SCREENSHOT")
        self.assertEqual(record["score"], 8)

        # 重跑同一分類必須冪等，不新增第二筆資料或覆寫其他目標。
        repeated = self.manager.register_review(
            self.job_id,
            self.group_id,
            "SCREENSHOT",
            self.media_path,
            score=8,
            reason="相同結果重跑",
        )
        self.assertEqual(repeated.review_entry_id, entry.review_entry_id)
        self.assertEqual(len(self.state.list_review_entries(self.job_id)), 1)

    def test_same_group_can_appear_in_multiple_review_categories(self):
        """同一群組可以在不同分類各有捷徑，但資料庫仍以 group_id 關聯。"""
        first = self.manager.register_review(
            self.job_id, self.group_id, "SCREENSHOT", self.media_path, score=8,
        )
        second = self.manager.register_review(
            self.job_id, self.group_id, "BLURRY", self.media_path, score=42,
        )
        self.assertNotEqual(first.review_entry_id, second.review_entry_id)
        self.assertEqual(len(self.state.list_review_entries(self.job_id)), 2)

    def test_json_and_external_targets_are_rejected(self):
        """JSON 不建立捷徑，允許根目錄外的媒體也不得登記。"""
        json_path = os.path.join(self.source_root, "測試照片.jpg.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            handle.write("{}")
        with self.assertRaises(ReviewWorkspaceError):
            self.manager.register_review(
                self.job_id, self.group_id, "SCREENSHOT", json_path,
            )

        external_path = os.path.join(self.root, "外部照片.jpg")
        with open(external_path, "wb") as handle:
            handle.write(b"external")
        with self.assertRaises(ReviewWorkspaceError):
            self.manager.register_review(
                self.job_id, self.group_id, "SCREENSHOT", external_path,
            )

    def test_existing_different_shortcut_is_never_overwritten(self):
        """同名捷徑若被竄改為其他目標，重跑必須報錯且保留原檔。"""
        entry = self.manager.register_review(
            self.job_id, self.group_id, "SCREENSHOT", self.media_path,
        )
        tampered_value = os.path.join(self.root, "惡意目標.jpg")
        with open(entry.shortcut_path, "w", encoding="utf-8") as handle:
            handle.write(tampered_value)

        with self.assertRaises(ReviewWorkspaceError):
            self.manager.register_review(
                self.job_id, self.group_id, "SCREENSHOT", self.media_path,
            )
        with open(entry.shortcut_path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), tampered_value)
        self.assertEqual(
            self.state.get_review_entry(entry.review_entry_id)["status"],
            "ERROR",
        )

    def test_moved_pending_delete_shortcut_still_validates_against_db(self):
        """使用者把已登記捷徑移至 99 後，仍能依 ID、目標及允許根目錄驗證。"""
        entry = self.manager.register_review(
            self.job_id, self.group_id, "SCREENSHOT", self.media_path,
        )
        pending_dir = os.path.join(
            self.manager.review_root,
            PENDING_DELETE_DIRECTORY,
        )
        moved_link = os.path.join(pending_dir, os.path.basename(entry.shortcut_path))
        os.rename(entry.shortcut_path, moved_link)

        valid, resolved_entry, error = self.manager.validate_registered_shortcut(moved_link)
        self.assertTrue(valid, error)
        self.assertEqual(resolved_entry.review_entry_id, entry.review_entry_id)

        # 竄改目標後必須拒絕。
        with open(moved_link, "w", encoding="utf-8") as handle:
            handle.write(os.path.join(self.root, "其他.jpg"))
        valid, _, error = self.manager.validate_registered_shortcut(moved_link)
        self.assertFalse(valid)
        self.assertIn("不一致", error)

    def test_dry_run_does_not_create_directories_links_or_db_rows(self):
        """DRY_RUN 只回傳預測結果，不留下 Workspace、捷徑或 SQLite 紀錄。"""
        dry_destination = os.path.join(self.root, "預覽結果")
        manager = ReviewWorkspaceManager(
            self.state,
            self.backend,
            dry_destination,
            allowed_source_roots=[self.source_root],
            dry_run=True,
        )
        entry = manager.register_review(
            self.job_id, self.group_id, "SCREENSHOT", self.media_path,
        )
        self.assertEqual(entry.status, "PREVIEW")
        self.assertFalse(os.path.exists(manager.review_root))
        self.assertIsNone(self.state.get_review_entry(entry.review_entry_id))

    def test_cache_directory_is_scoped_but_not_eagerly_created(self):
        """Phase 3 只規劃 ZIP 快取路徑，不提前實體化或全量解壓。"""
        cache_dir = self.manager.cache_directory_for(self.job_id, self.group_id)
        self.assertTrue(self.manager._is_within(cache_dir, self.manager.cache_root))
        self.assertFalse(os.path.exists(cache_dir))

    def test_cache_path_must_match_job_and_group_scope(self):
        """呼叫端不得把任意資料夾偽裝成 ZIP MediaGroup 的 ReviewCache。"""
        wrong_cache = os.path.join(self.manager.cache_root, "other-job", "other-group")
        with self.assertRaises(ReviewWorkspaceError):
            self.manager.register_review(
                self.job_id,
                self.group_id,
                "SCREENSHOT",
                self.media_path,
                cache_path=wrong_cache,
            )


if __name__ == "__main__":
    unittest.main()
