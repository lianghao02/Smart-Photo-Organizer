import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import datetime
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("webview", types.ModuleType("webview"))

from main import ConfigConstants, DateParser, ImageOps, Processor


class DateParserVideoMetadataTests(unittest.TestCase):
    def setUp(self):
        self.parser = DateParser()

    def test_quicktime_creation_date_has_priority(self):
        metadata = {
            "format": {"tags": {
                "creation_time": "2024-01-02T03:04:05Z",
                "com.apple.quicktime.creationdate": "2015-06-18T10:20:30+08:00",
            }},
            "streams": [],
        }
        actual = self.parser._parse_ffprobe_metadata(metadata)
        self.assertEqual(actual, datetime.datetime(2015, 6, 18, 10, 20, 30))

    def test_stream_creation_time_is_supported(self):
        metadata = {
            "format": {"tags": {}},
            "streams": [{"tags": {"creation_time": "2016-11-09T08:07:06"}}],
        }
        actual = self.parser._parse_ffprobe_metadata(metadata)
        self.assertEqual(actual, datetime.datetime(2016, 11, 9, 8, 7, 6))

    def test_invalid_metadata_returns_none(self):
        self.assertIsNone(self.parser._parse_ffprobe_metadata({"format": {"tags": {}}}))

    def test_original_exif_wins_over_google_json(self):
        candidates = [
            {"date": datetime.datetime(2020, 1, 1), "source": "Google Takeout JSON", "confidence": 95},
            {"date": datetime.datetime(2016, 5, 20), "source": "EXIF DateTimeOriginal", "confidence": 100},
        ]
        result = self.parser._select_date_candidate(candidates)
        self.assertEqual(result["date"], datetime.datetime(2016, 5, 20))
        self.assertEqual(result["source"], "EXIF DateTimeOriginal")

    def test_high_confidence_year_disagreement_is_conflict(self):
        candidates = [
            {"date": datetime.datetime(2016, 5, 20), "source": "EXIF DateTimeOriginal", "confidence": 100},
            {"date": datetime.datetime(2020, 1, 1), "source": "Google Takeout JSON", "confidence": 95},
        ]
        self.assertTrue(self.parser._select_date_candidate(candidates)["conflict"])

    def test_low_confidence_file_time_does_not_create_conflict(self):
        candidates = [
            {"date": datetime.datetime(2016, 5, 20), "source": "EXIF DateTimeOriginal", "confidence": 100},
            {"date": datetime.datetime(2026, 8, 7), "source": "Windows 檔案建立時間", "confidence": 20},
        ]
        self.assertFalse(self.parser._select_date_candidate(candidates)["conflict"])

    def test_generated_date_sequence_filename_is_not_evidence(self):
        self.assertIsNone(self.parser._get_filename_date_candidate("2026_07_23_304.jpg"))

    def test_duplicate_generated_filename_is_not_evidence(self):
        self.assertIsNone(self.parser._get_filename_date_candidate("DUP_2016_11_02_001.jpg"))

    def test_camera_filename_keeps_medium_confidence(self):
        candidate = self.parser._get_filename_date_candidate("IMG_20160520_123456.jpg")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate[1], "相機原生檔名日期")
        self.assertEqual(candidate[2], ConfigConstants.DATE_CONFIDENCE["camera_filename"])

    def test_generic_filename_date_is_low_confidence(self):
        candidate = self.parser._get_filename_date_candidate("旅行_2016-05-20.jpg")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate[2], ConfigConstants.DATE_CONFIDENCE["generic_filename"])


class ScreenshotScoringTests(unittest.TestCase):
    def test_screenshot_filename_reaches_threshold(self):
        score, reasons = ImageOps.score_excluded_screenshot("Screenshot_2016-01-01.png")
        self.assertGreaterEqual(score, ConfigConstants.EXCLUSION_SCORE_THRESHOLD)
        self.assertIn("截圖檔名(+7)", reasons)

    def test_surveillance_channel_filename_reaches_threshold(self):
        score, _ = ImageOps.score_excluded_screenshot("CAM01_20160520.jpg")
        self.assertGreaterEqual(score, ConfigConstants.EXCLUSION_SCORE_THRESHOLD)

    def test_ordinary_photo_filename_stays_below_threshold(self):
        score, _ = ImageOps.score_excluded_screenshot("IMG_20160520.jpg")
        self.assertLess(score, ConfigConstants.EXCLUSION_SCORE_THRESHOLD)


class SidecarTransferTests(unittest.TestCase):
    @staticmethod
    def _config(sidecar_enabled=True, mode="copy", dry_run=False):
        return {
            "mode": mode,
            "dry_run": dry_run,
            "resume_enabled": False,
            "sidecar_enabled": sidecar_enabled,
            "onedrive_protect": False,
            "src_root": "",
            "dst_root": "",
        }

    def test_copy_moves_both_supported_sidecar_names_with_media(self):
        project_dir = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=project_dir) as temp_dir:
            root = Path(temp_dir)
            src = root / "IMG_20160520.jpg"
            src.write_bytes(b"photo")
            (root / "IMG_20160520.jpg.json").write_text("{}", encoding="utf-8")
            (root / "IMG_20160520.json").write_text("{}", encoding="utf-8")
            dst = root / "out" / "2016_05_20_001.jpg"

            Processor(self._config())._execute(str(src), str(dst), "測試")

            self.assertTrue(dst.is_file())
            self.assertTrue(Path(str(dst) + ".json").is_file())
            self.assertTrue(dst.with_suffix(".json").is_file())
            self.assertTrue(src.is_file())

    def test_disabled_option_leaves_sidecar_unprocessed(self):
        project_dir = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=project_dir) as temp_dir:
            root = Path(temp_dir)
            src = root / "IMG_20160520.jpg"
            src.write_bytes(b"photo")
            sidecar = root / "IMG_20160520.jpg.json"
            sidecar.write_text("{}", encoding="utf-8")
            dst = root / "out" / "2016_05_20_001.jpg"

            Processor(self._config(sidecar_enabled=False))._execute(str(src), str(dst), "測試")

            self.assertTrue(dst.is_file())
            self.assertTrue(sidecar.is_file())
            self.assertFalse(Path(str(dst) + ".json").exists())

    def test_move_transfers_sidecar_and_removes_source_pair(self):
        project_dir = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=project_dir) as temp_dir:
            root = Path(temp_dir)
            src = root / "IMG_20160520.jpg"
            src.write_bytes(b"photo")
            sidecar = root / "IMG_20160520.jpg.json"
            sidecar.write_text("{}", encoding="utf-8")
            dst = root / "out" / "2016_05_20_001.jpg"

            Processor(self._config(mode="move"))._execute(str(src), str(dst), "測試")

            self.assertFalse(src.exists())
            self.assertFalse(sidecar.exists())
            self.assertTrue(dst.is_file())
            self.assertTrue(Path(str(dst) + ".json").is_file())

    def test_dry_run_only_records_sidecar_preview(self):
        project_dir = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=project_dir) as temp_dir:
            root = Path(temp_dir)
            src = root / "IMG_20160520.jpg"
            src.write_bytes(b"photo")
            sidecar = root / "IMG_20160520.jpg.json"
            sidecar.write_text("{}", encoding="utf-8")
            dst = root / "out" / "2016_05_20_001.jpg"
            processor = Processor(self._config(mode="move", dry_run=True))

            processor._execute(str(src), str(dst), "測試")

            self.assertTrue(src.is_file())
            self.assertTrue(sidecar.is_file())
            self.assertFalse(dst.exists())
            self.assertTrue(any(row[0] == str(sidecar) for row in processor.preview_log))


if __name__ == "__main__":
    unittest.main()
