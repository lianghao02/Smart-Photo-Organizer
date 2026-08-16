import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -*- coding: utf-8 -*-
"""v3.0 Phase 5 待刪除捷徑、MediaGroup 整組隔離與崩潰恢復測試。"""

import hashlib
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

from import_state import TakeoutStateManager
from quarantine_manager import QuarantineError, QuarantineManager
from review_workspace import PENDING_DELETE_DIRECTORY, ReviewWorkspaceManager


class FakeShortcutBackend:
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


class FailSecondRemovalManager(QuarantineManager):
    """模擬整組目的檔已完成後，移除第二個來源時中斷。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.removal_count = 0

    def _remove_verified_source(self, item, source_type, job_id, group_id):
        self.removal_count += 1
        if self.removal_count == 2:
            raise QuarantineError("模擬中斷")
        return super()._remove_verified_source(
            item, source_type, job_id, group_id
        )


class TestQuarantineManager(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.source_root = os.path.join(self.root, "來源")
        self.destination_root = os.path.join(self.root, "目標")
        os.makedirs(self.source_root)
        os.makedirs(self.destination_root)
        self.state = TakeoutStateManager(os.path.join(self.destination_root, "state.db"))
        self.backend = FakeShortcutBackend()
        self.workspace = ReviewWorkspaceManager(
            self.state,
            self.backend,
            self.destination_root,
            allowed_source_roots=[self.source_root],
        )
        self.workspace.initialize()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _sha256(path: str) -> str:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def _create_folder_group(self, job_id="job_q", group_id="mg_q"):
        media_path = os.path.join(self.source_root, f"{group_id}.jpg")
        json_path = media_path + ".json"
        with open(media_path, "wb") as handle:
            handle.write(b"photo-content")
        with open(json_path, "wb") as handle:
            handle.write(b'{"photoTakenTime": {"timestamp": "1"}}')
        self.state.create_job(
            job_id, "IMPORT", self.source_root, self.destination_root
        )
        media_key = f"folder:{group_id}.jpg"
        json_key = f"folder:{group_id}.jpg.json"
        self.state.create_media_group(
            group_id,
            job_id,
            None,
            "FOLDER",
            status="VALIDATED",
            members=[
                {"source_key": media_key, "role": "PRIMARY"},
                {"source_key": json_key, "role": "GOOGLE_JSON"},
            ],
        )
        entry = self.workspace.register_review(
            job_id,
            group_id,
            "SCREENSHOT",
            media_path,
            score=8,
        )
        pending_link = os.path.join(
            self.workspace.review_root,
            PENDING_DELETE_DIRECTORY,
            os.path.basename(entry.shortcut_path),
        )
        os.rename(entry.shortcut_path, pending_link)
        paths = {
            group_id: {
                media_key: media_path,
                json_key: json_path,
            }
        }
        return media_path, json_path, pending_link, paths

    def test_dry_run_plans_without_writing_or_moving(self):
        """預設 DRY_RUN 只回報完整群組與容量，不建立 Quarantine 或 SQLite 交易。"""
        media_path, json_path, pending_link, paths = self._create_folder_group()
        manager = QuarantineManager(
            self.state,
            self.workspace,
            self.destination_root,
            dry_run=True,
            free_space_reserve=0,
        )
        summary = manager.process_pending("job_q", paths)
        self.assertEqual(summary.planned_group_count, 1)
        self.assertEqual(summary.completed_group_count, 0)
        self.assertGreater(summary.planned_bytes, 0)
        self.assertTrue(os.path.isfile(media_path))
        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(pending_link))
        self.assertFalse(os.path.exists(manager.quarantine_root))
        self.assertIsNone(
            self.state.get_quarantine_action(manager._action_id("job_q", "mg_q"))
        )

    def test_full_group_moves_after_destination_verification(self):
        """媒體與 JSON 全部落地驗證後才移除來源，完成後不留下待刪除捷徑。"""
        media_path, json_path, pending_link, paths = self._create_folder_group()
        media_hash = self._sha256(media_path)
        json_hash = self._sha256(json_path)
        media_mtime = os.stat(media_path).st_mtime_ns
        manager = QuarantineManager(
            self.state,
            self.workspace,
            self.destination_root,
            dry_run=False,
            free_space_reserve=0,
        )
        summary = manager.process_pending("job_q", paths)
        self.assertEqual(summary.errors, [])
        self.assertEqual(summary.completed_group_count, 1)
        self.assertFalse(os.path.exists(media_path))
        self.assertFalse(os.path.exists(json_path))
        self.assertFalse(os.path.exists(pending_link))

        action = self.state.get_quarantine_action(
            manager._action_id("job_q", "mg_q")
        )
        self.assertEqual(action["status"], "COMPLETED")
        self.assertEqual(len(action["items"]), 2)
        destinations = {item["source_key"]: item["destination_path"] for item in action["items"]}
        self.assertEqual(self._sha256(destinations["folder:mg_q.jpg"]), media_hash)
        self.assertEqual(self._sha256(destinations["folder:mg_q.jpg.json"]), json_hash)
        self.assertEqual(os.stat(destinations["folder:mg_q.jpg"]).st_mtime_ns, media_mtime)
        self.assertEqual(self.state.get_media_group("mg_q")["status"], "QUARANTINED")
        review_entries = self.state.list_review_entries("job_q")
        self.assertTrue(all(entry["status"] == "QUARANTINED" for entry in review_entries))

    def test_multiple_category_links_process_group_only_once(self):
        """同一群組多個分類捷徑移入 99 時，實際隔離只能執行一次。"""
        media_path, json_path, _, paths = self._create_folder_group()
        second = self.workspace.register_review(
            "job_q", "mg_q", "BLURRY", media_path, score=12.5
        )
        second_pending = os.path.join(
            self.workspace.review_root,
            PENDING_DELETE_DIRECTORY,
            os.path.basename(second.shortcut_path),
        )
        os.rename(second.shortcut_path, second_pending)
        manager = QuarantineManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=0,
        )
        summary = manager.process_pending("job_q", paths)
        self.assertEqual(summary.discovered_link_count, 2)
        self.assertEqual(summary.planned_group_count, 1)
        self.assertEqual(summary.completed_group_count, 1)
        self.assertFalse(os.path.exists(media_path))
        self.assertFalse(os.path.exists(json_path))

    def test_missing_group_member_blocks_entire_move(self):
        """少一個 JSON 或 Live Photo 成員時禁止部分隔離，所有來源維持原狀。"""
        media_path, json_path, pending_link, paths = self._create_folder_group()
        del paths["mg_q"]["folder:mg_q.jpg.json"]
        manager = QuarantineManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=0,
        )
        summary = manager.process_pending("job_q", paths)
        self.assertEqual(summary.completed_group_count, 0)
        self.assertTrue(summary.errors)
        self.assertTrue(os.path.isfile(media_path))
        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(pending_link))

    def test_destination_conflict_never_overwrites_or_removes_source(self):
        """目的檔已有不同內容時立即停止，不覆寫也不移除任何來源成員。"""
        media_path, json_path, pending_link, paths = self._create_folder_group()
        manager = QuarantineManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=0,
        )
        conflict_dir = os.path.join(
            manager.quarantine_root, "job_q", "mg_q"
        )
        os.makedirs(conflict_dir, exist_ok=True)
        conflict_path = os.path.join(conflict_dir, "mg_q.jpg")
        with open(conflict_path, "wb") as handle:
            handle.write(b"different")

        summary = manager.process_pending("job_q", paths)
        self.assertTrue(summary.errors)
        with open(conflict_path, "rb") as handle:
            self.assertEqual(handle.read(), b"different")
        self.assertTrue(os.path.isfile(media_path))
        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(pending_link))

    def test_insufficient_space_stops_before_any_copy_or_source_removal(self):
        """磁碟空間不足時不得建立部分目的檔，也不得移除任何來源。"""
        media_path, json_path, pending_link, paths = self._create_folder_group()
        manager = QuarantineManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=100,
        )
        fake_usage = types.SimpleNamespace(total=1000, used=999, free=1)
        with patch("quarantine_manager.shutil.disk_usage", return_value=fake_usage):
            summary = manager.process_pending("job_q", paths)
        self.assertTrue(summary.errors)
        self.assertTrue(os.path.isfile(media_path))
        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(pending_link))
        destination_dir = os.path.join(manager.quarantine_root, "job_q", "mg_q")
        self.assertFalse(os.path.exists(destination_dir))

    def test_unregistered_shortcut_cannot_trigger_quarantine(self):
        """只有檔名看似合法但未登記於 SQLite 的捷徑不得觸發任何原檔操作。"""
        pending_dir = os.path.join(
            self.workspace.review_root,
            PENDING_DELETE_DIRECTORY,
        )
        forged_link = os.path.join(
            pending_dir,
            "re_000000000000000000000000__forged.jpg.lnk",
        )
        with open(forged_link, "w", encoding="utf-8") as handle:
            handle.write(os.path.join(self.source_root, "forged.jpg"))
        manager = QuarantineManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=0,
        )
        summary = manager.process_pending("unknown-job", {})
        self.assertEqual(summary.completed_group_count, 0)
        self.assertTrue(summary.errors)
        self.assertTrue(os.path.isfile(forged_link))

    def test_partial_source_removal_resumes_without_duplicate_output(self):
        """第一個來源已移除後中斷，重啟須重用已驗證目的檔並完成其餘成員。"""
        media_path, json_path, _, paths = self._create_folder_group()
        failing = FailSecondRemovalManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=0,
        )
        first_summary = failing.process_pending("job_q", paths)
        self.assertTrue(first_summary.errors)
        self.assertEqual(sum(os.path.exists(path) for path in (media_path, json_path)), 1)

        resumed = QuarantineManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=0,
        )
        second_summary = resumed.process_pending("job_q", paths)
        self.assertEqual(second_summary.errors, [])
        self.assertEqual(second_summary.completed_group_count, 1)
        self.assertFalse(os.path.exists(media_path))
        self.assertFalse(os.path.exists(json_path))
        action = self.state.get_quarantine_action(
            resumed._action_id("job_q", "mg_q")
        )
        self.assertEqual(action["status"], "COMPLETED")
        self.assertEqual(len(action["items"]), 2)

    def test_takeout_zip_stays_immutable_while_cache_group_moves(self):
        """Takeout 僅移動 ReviewCache 實體化群組；原始 ZIP 永遠保留且內容不變。"""
        job_id = "job_zip_q"
        group_id = "mg_zip_q"
        zip_path = os.path.join(self.source_root, "takeout.zip")
        with open(zip_path, "wb") as handle:
            handle.write(b"immutable-zip")
        zip_hash = self._sha256(zip_path)
        self.state.create_job(job_id, "IMPORT", self.source_root, self.destination_root)
        media_key = "zip:archive:1"
        json_key = "zip:archive:2"
        self.state.create_media_group(
            group_id, job_id, None, "TAKEOUT_ZIP", status="VALIDATED",
            members=[
                {"source_key": media_key, "role": "PRIMARY"},
                {"source_key": json_key, "role": "GOOGLE_JSON"},
            ],
        )
        cache_dir = self.workspace.cache_directory_for(job_id, group_id)
        os.makedirs(cache_dir, exist_ok=True)
        media_path = os.path.join(cache_dir, "photo.jpg")
        json_path = os.path.join(cache_dir, "photo.jpg.json")
        with open(media_path, "wb") as handle:
            handle.write(b"photo")
        with open(json_path, "wb") as handle:
            handle.write(b"json")
        entry = self.workspace.register_review(
            job_id, group_id, "SCREENSHOT", media_path,
            cache_path=cache_dir,
        )
        pending_link = os.path.join(
            self.workspace.review_root,
            PENDING_DELETE_DIRECTORY,
            os.path.basename(entry.shortcut_path),
        )
        os.rename(entry.shortcut_path, pending_link)
        manager = QuarantineManager(
            self.state, self.workspace, self.destination_root,
            dry_run=False, free_space_reserve=0,
        )
        summary = manager.process_pending(job_id, {
            group_id: {media_key: media_path, json_key: json_path}
        })
        self.assertEqual(summary.errors, [])
        self.assertEqual(summary.completed_group_count, 1)
        self.assertTrue(os.path.isfile(zip_path))
        self.assertEqual(self._sha256(zip_path), zip_hash)
        self.assertFalse(os.path.exists(media_path))
        self.assertFalse(os.path.exists(json_path))


if __name__ == "__main__":
    unittest.main()
