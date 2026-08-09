# -*- coding: utf-8 -*-
"""v3.0 Phase 8 日期異常 ReviewEntry 與 CSV 稽核測試。"""

import csv
import os
import shutil
import tempfile
import unittest

from PIL import Image

from date_review import DateAnomalyReviewer, DateReviewTarget
from import_state import TakeoutStateManager
from review_workspace import ReviewWorkspaceManager


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


class TestDateAnomalyReviewer(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.source_root = os.path.join(self.root, "來源")
        self.destination_root = os.path.join(self.root, "目標")
        os.makedirs(self.source_root)
        os.makedirs(self.destination_root)
        self.state = TakeoutStateManager(os.path.join(self.destination_root, "state.db"))
        self.job_id = "job_phase8"
        self.state.create_job(
            self.job_id,
            "IMPORT",
            self.source_root,
            self.destination_root,
        )
        self.workspace = ReviewWorkspaceManager(
            self.state,
            FakeShortcutBackend(),
            self.destination_root,
            allowed_source_roots=[self.source_root],
        )
        self.reviewer = DateAnomalyReviewer(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _target(
        self,
        group_id: str,
        capture_date="2020-05-20T10:00:00+08:00",
        source="EXIF DateTimeOriginal",
        confidence=100,
        conflict=False,
        filename=None,
    ) -> DateReviewTarget:
        filename = filename or f"{group_id}.jpg"
        path = os.path.join(self.source_root, filename)
        Image.new("RGB", (320, 240), "navy").save(path)
        self.state.create_media_group(
            group_id,
            self.job_id,
            None,
            "FOLDER",
            capture_date=capture_date,
            date_source=source,
            date_confidence=confidence,
            date_conflict=conflict,
            status="VALIDATED",
            members=[{
                "source_key": f"folder:{filename.lower()}",
                "role": "PRIMARY",
            }],
        )
        return DateReviewTarget(
            group_id,
            path,
            filename,
            capture_date,
            source,
            confidence,
            conflict,
        )

    def test_conflict_and_low_confidence_enter_date_review(self):
        conflict = self._target("mg_conflict", conflict=True)
        low = self._target("mg_low", confidence=49)
        result = self.reviewer.review(self.job_id, [conflict, low])
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.entries), 2)
        self.assertEqual({entry.category for entry in result.entries}, {"DATE_ANOMALY"})
        self.assertIn("衝突", next(e.reason for e in result.entries if e.group_id == "mg_conflict"))
        self.assertIn("49", next(e.reason for e in result.entries if e.group_id == "mg_low"))

    def test_missing_date_and_unknown_confidence_are_reviewed(self):
        missing = self._target("mg_missing", capture_date=None, confidence=0)
        unknown = self._target("mg_unknown", confidence=None)
        result = self.reviewer.review(self.job_id, [missing, unknown])
        self.assertEqual(len(result.entries), 2)
        self.assertIn("找不到", result.entries[0].reason + result.entries[1].reason)
        self.assertIn("未知", result.entries[0].reason + result.entries[1].reason)

    def test_confidence_equal_to_threshold_is_normal(self):
        normal = self._target("mg_threshold", confidence=50)
        result = self.reviewer.review(self.job_id, [normal])
        self.assertEqual(result.entries, [])
        self.assertTrue(os.path.isfile(result.audit_path))

    def test_audit_report_is_atomic_idempotent_and_excel_safe(self):
        unsafe = self._target(
            "mg_audit",
            filename="=HYPERLINK(惡意).jpg",
            confidence=40,
        )
        first = self.reviewer.review(self.job_id, [unsafe])
        second = self.reviewer.review(self.job_id, [unsafe])
        self.assertEqual(first.audit_path, second.audit_path)
        with open(second.audit_path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1][1].startswith("'="))
        self.assertFalse(any(name.endswith(".part") for name in os.listdir(self.workspace.review_root)))

    def test_source_media_is_unchanged(self):
        target = self._target("mg_unchanged", confidence=20)
        before = os.stat(target.target_path)
        with open(target.target_path, "rb") as handle:
            before_bytes = handle.read()
        self.reviewer.review(self.job_id, [target])
        after = os.stat(target.target_path)
        with open(target.target_path, "rb") as handle:
            after_bytes = handle.read()
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
        self.assertEqual(before_bytes, after_bytes)

    def test_date_conflict_is_persisted_in_media_group(self):
        self._target("mg_persisted", conflict=True)
        record = self.state.get_media_group("mg_persisted")
        self.assertEqual(record["date_conflict"], 1)

        # 來源重新索引通常不會再次解析日期，不得因此清空既有日期決策。
        self.state.create_media_group(
            "mg_persisted",
            self.job_id,
            None,
            "FOLDER",
            status="PAIRED",
            members=record["members"],
        )
        rescanned = self.state.get_media_group("mg_persisted")
        self.assertEqual(rescanned["capture_date"], "2020-05-20T10:00:00+08:00")
        self.assertEqual(rescanned["date_conflict"], 1)


if __name__ == "__main__":
    unittest.main()
