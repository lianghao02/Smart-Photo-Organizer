import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -*- coding: utf-8 -*-
"""v3.0 Phase 10 分析協調器端到端測試。"""

import datetime
import hashlib
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from PIL import Image, ImageDraw

from v3_pipeline import AnalysisOptions, PipelineCancelled, V3Pipeline
from takeout_zip import TakeoutZipScanner


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


class FakeDateParser:
    def get_date_details(self, path, is_photo, **kwargs):
        captured = datetime.datetime(2016, 5, 20, 10, 30)
        return {
            "date": captured,
            "source": "測試拍攝日期",
            "confidence": 100,
            "conflict": False,
            "candidates": [{
                "date": captured,
                "source": "測試拍攝日期",
                "confidence": 100,
            }],
        }


class TestV3Pipeline(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.source = os.path.join(self.root, "來源")
        self.destination = os.path.join(self.root, "目標")
        os.makedirs(self.source)
        os.makedirs(self.destination)
        self.backend = FakeShortcutBackend()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _sha256(path: str) -> str:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    @staticmethod
    def _image_bytes(size, altered=False, image_format="PNG") -> bytes:
        temporary = tempfile.NamedTemporaryFile(suffix="." + image_format.lower(), delete=False)
        temporary.close()
        try:
            image = Image.new("RGB", size, "white")
            if altered:
                draw = ImageDraw.Draw(image)
                draw.rectangle((10, 10, 25, 25), fill="red")
            image.save(temporary.name, format=image_format)
            with open(temporary.name, "rb") as handle:
                return handle.read()
        finally:
            os.remove(temporary.name)

    def _pipeline(self, source_path=None, mode="folder"):
        return V3Pipeline(
            source_path or self.source,
            self.destination,
            mode,
            self.backend,
            FakeDateParser(),
        )

    def test_folder_analysis_creates_review_without_touching_source(self):
        screenshot = os.path.join(self.source, "螢幕截圖.png")
        Image.new("RGB", (1080, 2400), "white").save(screenshot)
        sidecar = screenshot + ".json"
        with open(sidecar, "w", encoding="utf-8") as handle:
            handle.write('{"photoTakenTime":{"timestamp":"1463711400"}}')
        before_media = self._sha256(screenshot)
        before_json = self._sha256(sidecar)

        pipeline = self._pipeline()
        summary = pipeline.analyze(AnalysisOptions(
            blur_enabled=False,
            short_video_enabled=False,
            similar_enabled=False,
        ))
        self.assertEqual(summary.errors, [])
        self.assertEqual(summary.media_group_count, 1)
        self.assertEqual(summary.category_counts.get("SCREENSHOT"), 1)
        self.assertEqual(self._sha256(screenshot), before_media)
        self.assertEqual(self._sha256(sidecar), before_json)
        self.assertTrue(os.path.isfile(summary.date_audit_path))

    def test_takeout_streaming_keeps_cache_only_for_review_hits(self):
        zip_path = os.path.join(self.source, "takeout.zip")
        screenshot = self._image_bytes((1080, 2400))
        normal = self._image_bytes((800, 600))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Takeout/A/capture.png", screenshot)
            archive.writestr("Takeout/A/capture.png.json", '{"photoTakenTime":{"timestamp":"1"}}')
            archive.writestr("Takeout/B/photo.png", normal)
            archive.writestr("Takeout/B/photo.png.json", '{"photoTakenTime":{"timestamp":"1"}}')
        before_zip = self._sha256(zip_path)

        pipeline = self._pipeline(zip_path, "takeout_zip")
        summary = pipeline.analyze(AnalysisOptions(
            blur_enabled=False,
            short_video_enabled=False,
            similar_enabled=False,
        ))
        self.assertEqual(summary.errors, [])
        self.assertEqual(summary.media_group_count, 2)
        self.assertEqual(summary.cached_group_count, 1)
        cache_root = os.path.join(self.destination, "_ReviewCache", summary.job_id)
        cached_group_dirs = [
            name for name in os.listdir(cache_root)
            if os.path.isdir(os.path.join(cache_root, name))
        ]
        self.assertEqual(len(cached_group_dirs), 1)
        self.assertEqual(self._sha256(zip_path), before_zip)

    def test_takeout_analysis_failure_cleans_non_review_cache(self):
        zip_path = os.path.join(self.source, "failure.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Takeout/A/photo.png", self._image_bytes((800, 600)))

        pipeline = self._pipeline(zip_path, "takeout_zip")
        with patch.object(pipeline, "_resolve_date", side_effect=OSError("date failure")):
            summary = pipeline.analyze(AnalysisOptions(
                screenshot_enabled=False,
                blur_enabled=False,
                short_video_enabled=False,
                similar_enabled=False,
            ))

        self.assertEqual(len(summary.errors), 1)
        self.assertFalse(os.path.exists(
            os.path.join(self.destination, "_ReviewCache", summary.job_id)
        ))

    def test_takeout_exact_duplicates_reextract_only_duplicate_review_group(self):
        zip_path = os.path.join(self.source, "duplicates.zip")
        image_bytes = self._image_bytes((800, 600))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Takeout/A/photo.png", image_bytes)
            archive.writestr("Takeout/B/photo.png", image_bytes)
        pipeline = self._pipeline(zip_path, "takeout_zip")
        summary = pipeline.analyze(AnalysisOptions(
            screenshot_enabled=False,
            blur_enabled=False,
            short_video_enabled=False,
            similar_enabled=False,
        ))
        self.assertEqual(summary.errors, [])
        self.assertEqual(summary.category_counts.get("DUPLICATE"), 1)
        self.assertEqual(summary.cached_group_count, 1)

    def test_pending_delete_preview_then_execute_quarantine(self):
        screenshot = os.path.join(self.source, "screen.png")
        Image.new("RGB", (1080, 2400), "white").save(screenshot)
        pipeline = self._pipeline()
        summary = pipeline.analyze(AnalysisOptions(
            blur_enabled=False,
            short_video_enabled=False,
            similar_enabled=False,
        ))
        entry = pipeline.state.list_review_entries(summary.job_id, category="SCREENSHOT")[0]
        pending_dir = os.path.join(self.destination, "_Review", "99_待刪除")
        pending_link = os.path.join(pending_dir, os.path.basename(entry["shortcut_path"]))
        os.rename(entry["shortcut_path"], pending_link)

        preview = pipeline.process_pending_delete(dry_run=True)
        self.assertEqual(preview.planned_group_count, 1)
        self.assertTrue(os.path.isfile(screenshot))
        executed = pipeline.process_pending_delete(dry_run=False)
        self.assertEqual(executed.errors, [])
        self.assertEqual(executed.completed_group_count, 1)
        self.assertFalse(os.path.exists(screenshot))

    def test_restart_loads_latest_job_and_archive_preview_does_not_extract(self):
        photo = os.path.join(self.source, "photo.jpg")
        Image.new("RGB", (800, 600), "navy").save(photo)
        pipeline = self._pipeline()
        summary = pipeline.analyze(AnalysisOptions(
            screenshot_enabled=False,
            blur_enabled=False,
            short_video_enabled=False,
            similar_enabled=False,
        ))
        restarted = self._pipeline()
        context = restarted.load_latest_context()
        self.assertIsNotNone(context)
        self.assertEqual(context.job_id, summary.job_id)
        preview = restarted.preview_archive()
        self.assertEqual(preview.planned_group_count, 1)
        self.assertTrue(os.path.isfile(photo))

    def test_takeout_total_member_limit_is_enforced_before_analysis(self):
        zip_path = os.path.join(self.source, "too_many.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Takeout/A/one.jpg", b"one")
            archive.writestr("Takeout/A/two.jpg", b"two")
        pipeline = self._pipeline(zip_path, "takeout_zip")
        with patch.object(TakeoutZipScanner, "MAX_JOB_TOTAL_MEMBERS", 1):
            with self.assertRaisesRegex(ValueError, "成員總數超過安全上限"):
                pipeline._index_items()

    def test_pending_takeout_group_is_not_reextracted_during_archive(self):
        zip_path = os.path.join(self.source, "pending.zip")
        image_bytes = self._image_bytes((1080, 2400))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Takeout/A/screen.png", image_bytes)
        pipeline = self._pipeline(zip_path, "takeout_zip")
        summary = pipeline.analyze(AnalysisOptions(
            blur_enabled=False,
            short_video_enabled=False,
            similar_enabled=False,
        ))
        entry = pipeline.state.list_review_entries(
            summary.job_id,
            category="SCREENSHOT",
        )[0]
        pending_dir = os.path.join(self.destination, "_Review", "99_待刪除")
        pending_link = os.path.join(pending_dir, os.path.basename(entry["shortcut_path"]))
        os.rename(entry["shortcut_path"], pending_link)
        cache_root = os.path.join(self.destination, "_ReviewCache", summary.job_id)
        shutil.rmtree(cache_root)

        archived = pipeline.archive_by_date()
        self.assertEqual(archived.completed_group_count, 0)
        self.assertFalse(os.path.exists(cache_root))
        self.assertTrue(os.path.isfile(zip_path))

    def test_cancelled_analysis_resumes_the_same_job(self):
        photo = os.path.join(self.source, "resume.jpg")
        Image.new("RGB", (800, 600), "green").save(photo)
        stop = {"requested": True}
        pipeline = V3Pipeline(
            self.source,
            self.destination,
            "folder",
            self.backend,
            FakeDateParser(),
            cancel_check=lambda: stop["requested"],
        )
        with self.assertRaises(PipelineCancelled):
            pipeline.analyze(AnalysisOptions(
                screenshot_enabled=False,
                blur_enabled=False,
                short_video_enabled=False,
                similar_enabled=False,
            ))
        cancelled = pipeline.state.find_latest_job(
            self.source,
            self.destination,
            job_type="V3_FOLDER",
        )
        self.assertEqual(cancelled["status"], "CANCELLED")

        stop["requested"] = False
        resumed = pipeline.analyze(AnalysisOptions(
            screenshot_enabled=False,
            blur_enabled=False,
            short_video_enabled=False,
            similar_enabled=False,
        ))
        self.assertTrue(resumed.resumed_job)
        self.assertEqual(resumed.job_id, cancelled["job_id"])
        self.assertEqual(resumed.errors, [])


if __name__ == "__main__":
    unittest.main()
