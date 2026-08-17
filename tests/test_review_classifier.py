import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -*- coding: utf-8 -*-
"""v3.0 Phase 4 重複、模糊與截圖只建立 ReviewEntry／捷徑測試。"""

import hashlib
import os
import shutil
import tempfile
import unittest

from PIL import Image

from smart_photo_organizer.import_state import TakeoutStateManager
from smart_photo_organizer.media_group import GroupMember, GroupRole, MediaGroup
from smart_photo_organizer.review_classifier import (
    ExactDuplicateDetector,
    MediaAnalysisTarget,
    ReviewClassifier,
    VideoDurationProbe,
)
from smart_photo_organizer.review_workspace import ReviewWorkspaceManager
from smart_photo_organizer.source_index import SourceItem


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


class AlwaysBlurryDetector:
    @staticmethod
    def analyze(path: str, threshold: float):
        return True, 12.5, None


class UnavailableBlurDetector:
    @staticmethod
    def analyze(path: str, threshold: float):
        return None, 0.0, "未安裝 OpenCV／NumPy，已略過模糊分析"


class FakeDurationProbe:
    def __init__(self, duration, warning=None):
        self.duration = duration
        self.warning = warning
        self.call_count = 0

    def probe(self, path: str):
        self.call_count += 1
        return self.duration, self.warning


class TestReviewClassifier(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.source_root = os.path.join(self.root, "來源")
        self.destination_root = os.path.join(self.root, "目標")
        os.makedirs(self.source_root)
        os.makedirs(self.destination_root)
        self.state = TakeoutStateManager(os.path.join(self.destination_root, "state.db"))
        self.job_id = "job_phase4"
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

    def _register_group(self, group_id: str, paths):
        members = [
            {
                "source_key": f"folder:{os.path.basename(path).lower()}",
                "role": "PRIMARY" if index == 0 else "AUXILIARY",
            }
            for index, path in enumerate(paths)
        ]
        self.state.create_media_group(
            group_id,
            self.job_id,
            None,
            "FOLDER",
            status="VALIDATED",
            members=members,
        )

    @staticmethod
    def _sha256(path: str) -> str:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def test_exact_duplicate_uses_size_partial_and_full_hash(self):
        """部分雜湊相同但完整內容不同不得誤判；只標記決定性排序後的重複副本。"""
        first_path = os.path.join(self.source_root, "a.jpg")
        duplicate_path = os.path.join(self.source_root, "b.jpg")
        partial_collision_path = os.path.join(self.source_root, "c.jpg")
        original = bytearray(b"A" * 30000)
        collision = bytearray(original)
        collision[5000:6000] = b"B" * 1000
        for path, content in (
            (first_path, original),
            (duplicate_path, original),
            (partial_collision_path, collision),
        ):
            with open(path, "wb") as handle:
                handle.write(content)

        self._register_group("mg_a", [first_path])
        self._register_group("mg_b", [duplicate_path])
        self._register_group("mg_c", [partial_collision_path])
        classifier = ReviewClassifier(
            self.workspace,
            screenshot_enabled=False,
            blur_enabled=False,
        )
        result = classifier.classify(self.job_id, [
            MediaAnalysisTarget("mg_c", partial_collision_path),
            MediaAnalysisTarget("mg_b", duplicate_path),
            MediaAnalysisTarget("mg_a", first_path),
        ])

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].group_id, "mg_b")
        self.assertEqual(result.entries[0].category, "DUPLICATE")
        self.assertIn("mg_a", result.entries[0].reason)

    def test_live_photo_group_requires_all_media_to_match(self):
        """主照片相同但 Live Photo 影片不同時，整個 MediaGroup 不得視為完全重複。"""
        photo_a = os.path.join(self.source_root, "a.heic")
        photo_b = os.path.join(self.source_root, "b.heic")
        video_a = os.path.join(self.source_root, "a.mov")
        video_b = os.path.join(self.source_root, "b.mov")
        for path, content in (
            (photo_a, b"same-photo"),
            (photo_b, b"same-photo"),
            (video_a, b"video-one"),
            (video_b, b"video-two"),
        ):
            with open(path, "wb") as handle:
                handle.write(content)
        self._register_group("mg_live_a", [photo_a, video_a])
        self._register_group("mg_live_b", [photo_b, video_b])

        classifier = ReviewClassifier(
            self.workspace,
            screenshot_enabled=False,
            blur_enabled=False,
        )
        result = classifier.classify(self.job_id, [
            MediaAnalysisTarget("mg_live_a", photo_a, (photo_a, video_a)),
            MediaAnalysisTarget("mg_live_b", photo_b, (photo_b, video_b)),
        ])
        self.assertEqual(result.entries, [])

    def test_screenshot_score_creates_review_without_moving_media(self):
        """7 分截圖只進入 04 審核；來源檔案路徑與內容保持不變。"""
        screenshot = os.path.join(self.source_root, "2026_07_23_304.jpg")
        Image.new("RGB", (1080, 2400), "white").save(screenshot, quality=80)
        before_hash = self._sha256(screenshot)
        self._register_group("mg_screenshot", [screenshot])

        classifier = ReviewClassifier(
            self.workspace,
            screenshot_enabled=True,
            blur_enabled=False,
        )
        result = classifier.classify(
            self.job_id,
            [MediaAnalysisTarget("mg_screenshot", screenshot)],
        )
        screenshot_entries = [
            entry for entry in result.entries if entry.category == "SCREENSHOT"
        ]
        self.assertEqual(len(screenshot_entries), 1)
        self.assertGreaterEqual(screenshot_entries[0].score, 7)
        self.assertTrue(os.path.isfile(screenshot))
        self.assertEqual(self._sha256(screenshot), before_hash)

    def test_original_filename_is_used_for_cached_screenshot_evidence(self):
        """快取檔名即使不含關鍵字，仍須使用 Takeout 原始檔名進行截圖評分與顯示。"""
        cached_photo = os.path.join(self.source_root, "opaque-cache-name.jpg")
        Image.new("RGB", (400, 300), "white").save(cached_photo)
        self._register_group("mg_cached_screenshot", [cached_photo])
        classifier = ReviewClassifier(
            self.workspace,
            screenshot_enabled=True,
            blur_enabled=False,
        )
        result = classifier.classify(self.job_id, [MediaAnalysisTarget(
            "mg_cached_screenshot",
            cached_photo,
            original_filename="Screenshot_2026-08-09.jpg",
        )])
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].category, "SCREENSHOT")
        self.assertIn("Screenshot_2026-08-09.jpg", result.entries[0].shortcut_path)

    def test_hashing_rejects_media_changed_during_analysis(self):
        """檔案在 size 階段後被外部修改時，不得沿用舊快取產生重複判定。"""
        path = os.path.join(self.source_root, "changing.jpg")
        with open(path, "wb") as handle:
            handle.write(b"before")
        detector = ExactDuplicateDetector()
        detector._size(path)
        with open(path, "ab") as handle:
            handle.write(b"-changed")
        with self.assertRaises(OSError):
            detector._partial_hash(path)

    def test_blurry_candidate_creates_review_without_moving_media(self):
        """模糊候選只進入 03 審核，不直接移至 `_Blurry`。"""
        photo = os.path.join(self.source_root, "blurry.jpg")
        Image.new("RGB", (400, 300), "gray").save(photo)
        self._register_group("mg_blurry", [photo])
        classifier = ReviewClassifier(
            self.workspace,
            blur_detector=AlwaysBlurryDetector,
            screenshot_enabled=False,
            blur_enabled=True,
        )
        result = classifier.classify(
            self.job_id,
            [MediaAnalysisTarget("mg_blurry", photo)],
        )
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].category, "BLURRY")
        self.assertTrue(os.path.isfile(photo))
        self.assertFalse(os.path.exists(os.path.join(self.destination_root, "_Blurry")))

    def test_same_group_can_receive_screenshot_and_blurry_entries(self):
        """同一媒體符合多種候選時可建立多個捷徑，實體檔仍只有一份。"""
        photo = os.path.join(self.source_root, "Screenshot_001.png")
        Image.new("RGB", (1080, 2400), "white").save(photo)
        self._register_group("mg_multi", [photo])
        classifier = ReviewClassifier(
            self.workspace,
            blur_detector=AlwaysBlurryDetector,
        )
        result = classifier.classify(
            self.job_id,
            [MediaAnalysisTarget("mg_multi", photo)],
        )
        self.assertEqual(
            {entry.category for entry in result.entries},
            {"SCREENSHOT", "BLURRY"},
        )
        self.assertEqual(len(self.state.list_review_entries(self.job_id)), 2)
        self.assertTrue(os.path.isfile(photo))

    def test_blur_dependency_unavailable_is_warning_not_failure(self):
        """選用 OpenCV 未安裝時只記錄一次警告，其他分類仍可繼續。"""
        first = os.path.join(self.source_root, "first.jpg")
        second = os.path.join(self.source_root, "second.jpg")
        Image.new("RGB", (400, 300), "white").save(first)
        Image.new("RGB", (400, 300), "black").save(second)
        self._register_group("mg_first", [first])
        self._register_group("mg_second", [second])
        classifier = ReviewClassifier(
            self.workspace,
            blur_detector=UnavailableBlurDetector,
            screenshot_enabled=False,
        )
        result = classifier.classify(self.job_id, [
            MediaAnalysisTarget("mg_first", first),
            MediaAnalysisTarget("mg_second", second),
        ])
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.errors, [])

    def test_media_analysis_target_excludes_json_but_keeps_live_photo_video(self):
        """由 MediaGroup 建立分析目標時，JSON 不參與重複雜湊，Live Photo 影片會保留。"""
        photo_path = os.path.join(self.source_root, "live.heic")
        video_path = os.path.join(self.source_root, "live.mov")
        json_path = os.path.join(self.source_root, "live.heic.json")
        for path in (photo_path, video_path, json_path):
            with open(path, "wb") as handle:
                handle.write(b"data")
        photo_item = SourceItem("p", "FOLDER", "live.heic", "live.heic", ".heic", 4, True, False, abs_path=photo_path)
        video_item = SourceItem("v", "FOLDER", "live.mov", "live.mov", ".mov", 4, True, False, abs_path=video_path)
        json_item = SourceItem("j", "FOLDER", "live.heic.json", "live.heic.json", ".json", 4, False, True, abs_path=json_path)
        group = MediaGroup(
            "mg_live",
            photo_item,
            "FOLDER",
            members=[
                GroupMember(photo_item, GroupRole.PRIMARY),
                GroupMember(video_item, GroupRole.LIVE_PHOTO_VIDEO),
                GroupMember(json_item, GroupRole.GOOGLE_JSON),
            ],
        )

        target = MediaAnalysisTarget.from_media_group(group)
        self.assertEqual(set(target.all_media_paths()), {photo_path, video_path})
        self.assertNotIn(json_path, target.all_media_paths())

    def test_incomplete_live_photo_group_is_rejected(self):
        """ZIP Live Photo 若只實體化主照片、未提供配對影片，不得降級成單檔重複判定。"""
        cached_photo = os.path.join(self.source_root, "cached.heic")
        with open(cached_photo, "wb") as handle:
            handle.write(b"photo")
        photo_item = SourceItem(
            "p", "TAKEOUT_ZIP", "live.heic", "live.heic", ".heic", 5,
            True, False, archive_fingerprint="archive-a",
        )
        video_item = SourceItem(
            "v", "TAKEOUT_ZIP", "live.mov", "live.mov", ".mov", 5,
            True, False, archive_fingerprint="archive-a",
        )
        group = MediaGroup(
            "mg_incomplete",
            photo_item,
            "TAKEOUT_ZIP",
            members=[
                GroupMember(photo_item, GroupRole.PRIMARY),
                GroupMember(video_item, GroupRole.LIVE_PHOTO_VIDEO),
            ],
        )
        with self.assertRaises(ValueError):
            MediaAnalysisTarget.from_media_group(
                group,
                resolved_paths={"p": cached_photo},
            )

    def test_five_second_video_creates_short_video_review(self):
        """影片長度等於 5 秒仍應列入 05_短影片，來源檔保持不變。"""
        video = os.path.join(self.source_root, "clip.mp4")
        with open(video, "wb") as handle:
            handle.write(b"video")
        self._register_group("mg_short", [video])
        probe = FakeDurationProbe(5.0)
        classifier = ReviewClassifier(
            self.workspace,
            duration_probe=probe,
            screenshot_enabled=False,
            blur_enabled=False,
        )
        result = classifier.classify(
            self.job_id,
            [MediaAnalysisTarget("mg_short", video, original_filename="clip.mp4")],
        )
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].category, "SHORT_VIDEO")
        self.assertEqual(result.entries[0].score, 5.0)
        self.assertTrue(os.path.isfile(video))

    def test_video_longer_than_five_seconds_is_not_reviewed(self):
        """5.001 秒不符合小於或等於 5 秒規則。"""
        video = os.path.join(self.source_root, "long.mp4")
        with open(video, "wb") as handle:
            handle.write(b"video")
        self._register_group("mg_long", [video])
        classifier = ReviewClassifier(
            self.workspace,
            duration_probe=FakeDurationProbe(5.001),
            screenshot_enabled=False,
            blur_enabled=False,
        )
        result = classifier.classify(
            self.job_id,
            [MediaAnalysisTarget("mg_long", video)],
        )
        self.assertEqual(result.entries, [])

    def test_live_photo_video_is_excluded_before_duration_probe(self):
        """LIVE_PHOTO_VIDEO 即使小於 5 秒，也不得呼叫 duration 分類或建立捷徑。"""
        video = os.path.join(self.source_root, "live.mov")
        with open(video, "wb") as handle:
            handle.write(b"video")
        self._register_group("mg_live_video", [video])
        probe = FakeDurationProbe(1.0)
        classifier = ReviewClassifier(
            self.workspace,
            duration_probe=probe,
            screenshot_enabled=False,
            blur_enabled=False,
        )
        result = classifier.classify(self.job_id, [MediaAnalysisTarget(
            "mg_live_video",
            video,
            contains_live_photo_video=True,
        )])
        self.assertEqual(result.entries, [])
        self.assertEqual(probe.call_count, 0)

    def test_duration_probe_parsing_prefers_container_then_longest_stream(self):
        """容器 duration 優先；容器缺少時採有效串流的最長秒數。"""
        self.assertEqual(
            VideoDurationProbe.parse_duration({
                "format": {"duration": "4.5"},
                "streams": [{"duration": "9.0"}],
            }),
            4.5,
        )
        self.assertEqual(
            VideoDurationProbe.parse_duration({
                "format": {},
                "streams": [{"duration": "2.0"}, {"duration": "3.5"}],
            }),
            3.5,
        )
        self.assertIsNone(VideoDurationProbe.parse_duration({"format": {}}))

    def test_duration_probe_failure_is_warning_not_short_video(self):
        """ffprobe 失敗只記錄警告，不得把未知長度影片當成短影片。"""
        video = os.path.join(self.source_root, "unknown.mp4")
        with open(video, "wb") as handle:
            handle.write(b"video")
        self._register_group("mg_unknown", [video])
        classifier = ReviewClassifier(
            self.workspace,
            duration_probe=FakeDurationProbe(None, "找不到 ffprobe"),
            screenshot_enabled=False,
            blur_enabled=False,
        )
        result = classifier.classify(
            self.job_id,
            [MediaAnalysisTarget("mg_unknown", video)],
        )
        self.assertEqual(result.entries, [])
        self.assertEqual(len(result.warnings), 1)


if __name__ == "__main__":
    unittest.main()
