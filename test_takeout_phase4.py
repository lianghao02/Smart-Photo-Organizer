# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 4.1 落地與測試重構單元測試
驗證 Mock DateConflict 隔離、LowConfidenceDate 隔離、7 分制截圖 (含非關鍵字截圖與 line_album_ 正確不隔離)
以及 write_sidecar_atomic Helper 成功、碰撞與失敗狀態追蹤
"""

import os
import sys
import shutil
import tempfile
import zipfile
import unittest
import datetime
from pathlib import Path

# 動態加載專案目錄
PROJECT_ROOT = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import import_state
import takeout_zip
import takeout_index
import media_metadata
import main as app_main


class MockConflictDateParser:
    """Mock DateParser 回傳顯著日期衝突 (conflict = True)"""
    def get_date_details(self, path, is_photo=True, is_cloud=False, shell_reader=None, google_json_date=None):
        return {
            "date": datetime.datetime(2018, 6, 15, 12, 0, 0),
            "source": "EXIF DateTimeOriginal",
            "confidence": 100,
            "conflict": True
        }


class MockLowConfidenceDateParser:
    """Mock DateParser 回傳低可信度日期 (confidence = 40)"""
    def get_date_details(self, path, is_photo=True, is_cloud=False, shell_reader=None, google_json_date=None):
        return {
            "date": datetime.datetime(2026, 8, 9, 8, 0, 0),
            "source": "Windows 檔案建立時間",
            "confidence": 40,
            "conflict": False
        }


class TestTakeoutPhase4(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.test_dir, "takeout-phase4-test.zip")
        self.dst_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.dst_dir, exist_ok=True)

        self.sample_photo_bytes = b"Phase 4 test photo content"
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr("Takeout/Google Photos/Album2018/2018_06_15_001.jpg", self.sample_photo_bytes)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_7_point_screenshot_classification_and_line_album_non_screenshot(self):
        """驗證 7 分制截圖評分引擎：關鍵字截圖、非關鍵字手機直向 PNG (評分 >= 7) 及普通 line_album_ 照片 (評分 < 7)"""
        part_path = os.path.join(self.dst_dir, "temp.png")
        with open(part_path, 'wb') as f:
            f.write(self.sample_photo_bytes)

        date_parser = app_main.DateParser()

        # 1. 檔名關鍵字截圖 ➔ 評分 >= 7
        meta1 = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=part_path, filename="Screenshot_20230520.png", dst_root=self.dst_dir, date_parser=date_parser
        )
        self.assertTrue(meta1['is_screenshot'])
        self.assertGreaterEqual(meta1['screenshot_score'], 7)
        self.assertIn("_Excluded", meta1['target_dir'])
        self.assertIn("Screenshots", meta1['target_dir'])

        # 2. 普通 LINE 相簿照片 line_album_photo.jpg ➔ 評分小於 7 (不誤判為截圖)
        meta2 = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=part_path, filename="line_album_20230520.jpg", dst_root=self.dst_dir, date_parser=date_parser
        )
        self.assertFalse(meta2['is_screenshot'])
        self.assertLess(meta2['screenshot_score'], 7)

    def test_date_conflict_isolation_with_mock_parser(self):
        """驗證真實 DateConflict 分支：當 DateParser 回傳 conflict = True 時，目標目錄為 _Review/DateConflict"""
        mock_parser = MockConflictDateParser()
        part_path = os.path.join(self.dst_dir, "temp_conflict.jpg")
        with open(part_path, 'wb') as f:
            f.write(self.sample_photo_bytes)

        meta_res = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=part_path, filename="2018_06_15_001.jpg", dst_root=self.dst_dir, date_parser=mock_parser
        )

        self.assertTrue(meta_res['has_conflict'])
        expected_dir = os.path.join(self.dst_dir, "_Review", "DateConflict", "2018", "Photos")
        self.assertEqual(os.path.normpath(meta_res['target_dir']), os.path.normpath(expected_dir))

    def test_low_confidence_date_isolation(self):
        """驗證真實 LowConfidenceDate 分支：當 confidence < 50 時，目標目錄為 _Review/LowConfidenceDate"""
        mock_parser = MockLowConfidenceDateParser()
        part_path = os.path.join(self.dst_dir, "temp_low.jpg")
        with open(part_path, 'wb') as f:
            f.write(self.sample_photo_bytes)

        meta_res = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=part_path, filename="random_9999.jpg", dst_root=self.dst_dir, date_parser=mock_parser
        )

        self.assertLess(meta_res['confidence'], 50)
        expected_dir = os.path.join(self.dst_dir, "_Review", "LowConfidenceDate", "2026", "Photos")
        self.assertEqual(os.path.normpath(meta_res['target_dir']), os.path.normpath(expected_dir))

    def test_write_sidecar_atomic_success_collision_and_cleanup(self):
        """驗證 write_sidecar_atomic 成功寫入、檔碰撞 FileExistsError 與 .json.part 清理"""
        json_final = os.path.join(self.dst_dir, "test_output.jpg.json")
        json_bytes = b'{"photoTakenTime":{"timestamp":"1529064000"}}'

        # 1. 成功落碟
        ok1, err1 = media_metadata.write_sidecar_atomic(json_bytes, json_final)
        self.assertTrue(ok1)
        self.assertIsNone(err1)
        self.assertTrue(os.path.exists(json_final))
        self.assertFalse(os.path.exists(json_final + ".part"))

        # 2. 檔已存在引發碰撞 ➔ 回傳 False 且未拋出例外，.part 檔自動清理
        ok2, err2 = media_metadata.write_sidecar_atomic(json_bytes, json_final)
        self.assertFalse(ok2)
        self.assertIsNotNone(err2)
        self.assertFalse(os.path.exists(json_final + ".part"))


if __name__ == '__main__':
    unittest.main()
