# -*- coding: utf-8 -*-
"""v3.0 Phase 7 時間分桶與感知雜湊相似照片測試。"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

from import_state import TakeoutStateManager
from review_classifier import MediaAnalysisTarget, ReviewClassifier
from review_workspace import ReviewWorkspaceManager
from similarity import SimilarPhotoDetector, SimilarityCandidate


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


class TestSimilarPhotoDetector(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.source_root = os.path.join(self.root, "來源")
        self.destination_root = os.path.join(self.root, "目標")
        os.makedirs(self.source_root)
        os.makedirs(self.destination_root)
        self.state = TakeoutStateManager(os.path.join(self.destination_root, "state.db"))
        self.job_id = "job_phase7"
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

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _image(self, name: str, size=(800, 600), altered=False) -> str:
        path = os.path.join(self.source_root, name)
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        for offset in range(0, size[0], 80):
            draw.rectangle((offset, 0, min(offset + 39, size[0] - 1), size[1]), fill="navy")
        if altered:
            draw.rectangle((10, 10, 18, 18), fill="red")
        image.save(path, compress_level=6)
        return path

    def _register_group(self, group_id: str, path: str) -> None:
        self.state.create_media_group(
            group_id,
            self.job_id,
            None,
            "FOLDER",
            status="VALIDATED",
            members=[{
                "source_key": f"folder:{os.path.basename(path).lower()}",
                "role": "PRIMARY",
            }],
        )

    @staticmethod
    def _read_bytes(path: str) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()

    def test_similar_within_time_window_creates_two_review_links(self):
        first = self._image("first.png")
        second = self._image("second.png", altered=True)
        self._register_group("mg_first", first)
        self._register_group("mg_second", second)
        before_first = self._read_bytes(first)
        before_second = self._read_bytes(second)

        classifier = ReviewClassifier(
            self.workspace,
            screenshot_enabled=False,
            blur_enabled=False,
            short_video_enabled=False,
        )
        result = classifier.classify(self.job_id, [
            MediaAnalysisTarget(
                "mg_first",
                first,
                capture_date="2026-08-09T10:00:00+08:00",
            ),
            MediaAnalysisTarget(
                "mg_second",
                second,
                capture_date="2026-08-09T10:05:00+08:00",
            ),
        ])

        similar_entries = [entry for entry in result.entries if entry.category == "SIMILAR"]
        self.assertEqual(result.errors, [])
        self.assertEqual(len(similar_entries), 2)
        self.assertEqual({entry.group_id for entry in similar_entries}, {"mg_first", "mg_second"})
        self.assertEqual(self._read_bytes(first), before_first)
        self.assertEqual(self._read_bytes(second), before_second)

    def test_same_visual_outside_time_window_is_not_compared_as_similar(self):
        first = self._image("early.png")
        second = self._image("late.png", altered=True)
        detector = SimilarPhotoDetector(time_window_seconds=900)
        result = detector.find_similar([
            SimilarityCandidate("mg_early", first, "2026-08-09T10:00:00+08:00"),
            SimilarityCandidate("mg_late", second, "2026-08-09T11:00:00+08:00"),
        ])
        self.assertEqual(result.findings, {})

    def test_incompatible_dimensions_are_rejected_before_similarity(self):
        landscape = self._image("landscape.png", (800, 600))
        portrait = self._image("portrait.png", (600, 800), altered=True)
        detector = SimilarPhotoDetector()
        result = detector.find_similar([
            SimilarityCandidate("mg_landscape", landscape, "2026-08-09T10:00:00"),
            SimilarityCandidate("mg_portrait", portrait, "2026-08-09T10:01:00"),
        ])
        self.assertEqual(result.findings, {})

    def test_exact_duplicate_is_left_to_duplicate_category(self):
        first = self._image("copy_a.png")
        second = os.path.join(self.source_root, "copy_b.png")
        shutil.copyfile(first, second)
        detector = SimilarPhotoDetector()
        result = detector.find_similar([
            SimilarityCandidate("mg_copy_a", first, "2026-08-09T10:00:00"),
            SimilarityCandidate("mg_copy_b", second, "2026-08-09T10:01:00"),
        ])
        self.assertEqual(result.findings, {})

    def test_time_and_hash_index_avoid_whole_library_quadratic_comparison(self):
        base = datetime(2026, 8, 9, tzinfo=timezone.utc)
        candidates = []
        for index in range(60):
            path = self._image(f"batch_{index:03d}.png", altered=bool(index % 2))
            candidates.append(SimilarityCandidate(
                f"mg_{index:03d}",
                path,
                (base + timedelta(minutes=index * 20)).isoformat(),
            ))
        detector = SimilarPhotoDetector(time_window_seconds=900)
        result = detector.find_similar(candidates)
        whole_library_pairs = len(candidates) * (len(candidates) - 1) // 2
        self.assertLess(result.comparison_count, whole_library_pairs // 10)


if __name__ == "__main__":
    unittest.main()
