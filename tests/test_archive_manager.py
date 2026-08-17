import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -*- coding: utf-8 -*-
"""v3.0 Phase 9 MediaGroup 整組日期歸檔與恢復測試。"""

import hashlib
import os
import shutil
import tempfile
import unittest

from smart_photo_organizer.archive_manager import ArchiveError, MediaArchiveManager
from smart_photo_organizer.import_state import TakeoutStateManager
from smart_photo_organizer.review_workspace import PENDING_DELETE_DIRECTORY, ReviewWorkspaceManager


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


class FailSecondRemovalArchive(MediaArchiveManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.removal_count = 0

    def _remove_verified_source(self, item, source_type, job_id, group_id):
        self.removal_count += 1
        if self.removal_count == 2:
            raise ArchiveError("模擬移除來源時中斷")
        return super()._remove_verified_source(item, source_type, job_id, group_id)


class FailSecondCopyArchive(MediaArchiveManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.copy_count = 0

    def _copy_and_verify(self, item):
        self.copy_count += 1
        if self.copy_count == 2:
            raise ArchiveError("模擬第二個成員複製失敗")
        return super()._copy_and_verify(item)


class TestMediaArchiveManager(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.source_root = os.path.join(self.root, "來源")
        self.destination_root = os.path.join(self.root, "目標")
        os.makedirs(self.source_root)
        os.makedirs(self.destination_root)
        self.state = TakeoutStateManager(os.path.join(self.destination_root, "state.db"))
        self.job_id = "job_phase9"
        self.state.create_job(
            self.job_id,
            "IMPORT",
            self.source_root,
            self.destination_root,
        )
        self.backend = FakeShortcutBackend()
        self.workspace = ReviewWorkspaceManager(
            self.state,
            self.backend,
            self.destination_root,
            allowed_source_roots=[self.source_root],
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _sha256(path: str) -> str:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def _create_group(
        self,
        group_id="mg_archive",
        filenames=("IMG_001.jpg", "IMG_001.jpg.json"),
        source_type="FOLDER",
        capture_date="2015-06-20T10:30:00+08:00",
        confidence=100,
        conflict=False,
        source_directory=None,
        roles=None,
    ):
        source_directory = source_directory or self.source_root
        os.makedirs(source_directory, exist_ok=True)
        roles = roles or ["PRIMARY"] + ["GOOGLE_JSON"] * (len(filenames) - 1)
        members = []
        paths = {}
        for index, filename in enumerate(filenames):
            path = os.path.join(source_directory, filename)
            with open(path, "wb") as handle:
                handle.write(f"content-{group_id}-{index}".encode("utf-8"))
            key = f"{source_type.lower()}:{group_id}:{index}"
            paths[key] = path
            members.append({"source_key": key, "role": roles[index]})
        self.state.create_media_group(
            group_id,
            self.job_id,
            None,
            source_type,
            capture_date=capture_date,
            date_source="EXIF DateTimeOriginal",
            date_confidence=confidence,
            date_conflict=conflict,
            status="VALIDATED",
            members=members,
        )
        return {group_id: paths}

    def _manager(self, dry_run=False, manager_class=MediaArchiveManager):
        return manager_class(
            self.state,
            self.workspace,
            self.destination_root,
            dry_run=dry_run,
            free_space_reserve=0,
        )

    def test_dry_run_plans_without_writing_or_moving(self):
        paths = self._create_group()
        originals = list(paths["mg_archive"].values())
        manager = self._manager(dry_run=True)
        summary = manager.archive_groups(self.job_id, paths)
        self.assertEqual(summary.planned_group_count, 1)
        self.assertEqual(summary.completed_group_count, 0)
        self.assertTrue(all(os.path.isfile(path) for path in originals))
        self.assertFalse(os.path.exists(os.path.join(self.destination_root, "2015")))
        self.assertIsNone(self.state.get_archive_action(manager._action_id(self.job_id, "mg_archive")))

    def test_photo_and_json_move_together_to_year_month_photos(self):
        paths = self._create_group()
        originals = paths["mg_archive"]
        media_path = next(iter(originals.values()))
        review_entry = self.workspace.register_review(
            self.job_id,
            "mg_archive",
            "SCREENSHOT",
            media_path,
            score=8,
        )
        hashes = {key: self._sha256(path) for key, path in originals.items()}
        summary = self._manager().archive_groups(self.job_id, paths)
        self.assertEqual(summary.errors, [])
        self.assertEqual(summary.completed_group_count, 1)
        action = self.state.get_archive_action(
            MediaArchiveManager._action_id(self.job_id, "mg_archive")
        )
        self.assertEqual(action["status"], "COMPLETED")
        self.assertEqual(action["destination_dir"], os.path.join(
            self.destination_root, "2015", "06", "Photos"
        ))
        for item in action["items"]:
            self.assertFalse(os.path.exists(item["source_path"]))
            self.assertEqual(self._sha256(item["destination_path"]), hashes[item["source_key"]])
        self.assertEqual(self.state.get_media_group("mg_archive")["status"], "ARCHIVED")
        self.assertFalse(os.path.exists(review_entry.shortcut_path))
        self.assertEqual(
            self.state.get_review_entry(review_entry.review_entry_id)["status"],
            "ARCHIVED",
        )

    def test_live_photo_and_json_remain_one_photos_group(self):
        paths = self._create_group(
            "mg_live",
            ("IMG_002.heic", "IMG_002.mov", "IMG_002.heic.json"),
            roles=("PRIMARY", "LIVE_PHOTO_VIDEO", "GOOGLE_JSON"),
        )
        summary = self._manager().archive_groups(self.job_id, paths)
        self.assertEqual(summary.errors, [])
        action = self.state.get_archive_action(
            MediaArchiveManager._action_id(self.job_id, "mg_live")
        )
        self.assertTrue(action["destination_dir"].endswith(os.path.join("06", "Photos")))
        self.assertEqual(len(action["items"]), 3)

    def test_name_collision_uses_one_group_suffix_without_overwrite(self):
        paths = self._create_group()
        destination = os.path.join(self.destination_root, "2015", "06", "Photos")
        os.makedirs(destination, exist_ok=True)
        existing = os.path.join(destination, "IMG_001.jpg")
        with open(existing, "wb") as handle:
            handle.write(b"existing-must-stay")
        summary = self._manager().archive_groups(self.job_id, paths)
        self.assertEqual(summary.errors, [])
        with open(existing, "rb") as handle:
            self.assertEqual(handle.read(), b"existing-must-stay")
        action = self.state.get_archive_action(
            MediaArchiveManager._action_id(self.job_id, "mg_archive")
        )
        names = [os.path.basename(item["destination_path"]) for item in action["items"]]
        media_name = next(name for name in names if name.endswith(".jpg"))
        sidecar_name = next(name for name in names if name.endswith(".jpg.json"))
        suffixed_stem = os.path.splitext(media_name)[0]
        self.assertTrue(sidecar_name.startswith(suffixed_stem + ".jpg"))

    def test_low_confidence_or_conflict_never_moves(self):
        low = self._create_group("mg_low", confidence=49)
        conflict = self._create_group("mg_conflict", conflict=True)
        paths = {**low, **conflict}
        summary = self._manager().archive_groups(self.job_id, paths)
        self.assertEqual(summary.completed_group_count, 0)
        self.assertEqual(len(summary.errors), 2)
        self.assertTrue(all(
            os.path.isfile(path)
            for group_paths in paths.values()
            for path in group_paths.values()
        ))

    def test_pending_delete_group_is_skipped_until_quarantine(self):
        paths = self._create_group()
        media_path = next(iter(paths["mg_archive"].values()))
        entry = self.workspace.register_review(
            self.job_id,
            "mg_archive",
            "BLURRY",
            media_path,
            score=10,
        )
        pending = os.path.join(
            self.workspace.review_root,
            PENDING_DELETE_DIRECTORY,
            os.path.basename(entry.shortcut_path),
        )
        os.rename(entry.shortcut_path, pending)
        summary = self._manager().archive_groups(self.job_id, paths)
        self.assertEqual(summary.planned_group_count, 0)
        self.assertEqual(summary.skipped_group_count, 1)
        self.assertTrue(os.path.isfile(media_path))

    def test_interrupted_source_removal_resumes_without_second_copy(self):
        paths = self._create_group()
        first = self._manager(manager_class=FailSecondRemovalArchive)
        failed = first.archive_groups(self.job_id, paths)
        self.assertEqual(len(failed.errors), 1)
        action_id = MediaArchiveManager._action_id(self.job_id, "mg_archive")
        interrupted = self.state.get_archive_action(action_id)
        self.assertIn(interrupted["status"], {"FAILED", "REMOVING_SOURCE"})
        self.assertTrue(all(os.path.isfile(item["destination_path"]) for item in interrupted["items"]))

        resumed = self._manager().archive_groups(self.job_id, paths)
        self.assertEqual(resumed.errors, [])
        self.assertEqual(resumed.completed_group_count, 1)
        completed = self.state.get_archive_action(action_id)
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertTrue(all(not os.path.exists(item["source_path"]) for item in completed["items"]))

    def test_copy_failure_keeps_every_source_member(self):
        paths = self._create_group("mg_copy_failure")
        sources = list(paths["mg_copy_failure"].values())
        failed = self._manager(
            manager_class=FailSecondCopyArchive
        ).archive_groups(self.job_id, paths)
        self.assertEqual(len(failed.errors), 1)
        self.assertTrue(all(os.path.isfile(path) for path in sources))

    def test_takeout_zip_archives_cache_but_keeps_original_zip(self):
        zip_path = os.path.join(self.source_root, "takeout.zip")
        with open(zip_path, "wb") as handle:
            handle.write(b"immutable-zip")
        before_hash = self._sha256(zip_path)
        cache = self.workspace.cache_directory_for(self.job_id, "mg_zip")
        paths = self._create_group(
            "mg_zip",
            source_type="TAKEOUT_ZIP",
            source_directory=cache,
        )
        summary = self._manager().archive_groups(self.job_id, paths)
        self.assertEqual(summary.errors, [])
        self.assertTrue(os.path.isfile(zip_path))
        self.assertEqual(self._sha256(zip_path), before_hash)


if __name__ == "__main__":
    unittest.main()
