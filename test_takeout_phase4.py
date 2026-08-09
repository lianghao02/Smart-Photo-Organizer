# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 4.2 精準截圖引擎與 COMPLETED_WITH_ERRORS 續傳保護測試
驗證真實 1080x2400 無關鍵字 PNG/JPG 截圖 (評分 >= 7)、line_album_ 照片 (評分 < 7)、Mock DateConflict/LowConfidenceDate 與 Sidecar 失敗後續傳保護
"""

import os
import sys
import shutil
import tempfile
import zipfile
import unittest
import datetime
from pathlib import Path
from PIL import Image

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

    def test_non_keyword_1080x2400_screenshot_scoring(self):
        """驗證真實 1080x2400 無關鍵字截圖 (PNG 評分 8 分, JPG 評分 7 分) 正確劃入 Screenshots 隔離區"""
        # 1. 建立真實 1080x2400 PNG 無 EXIF 圖片
        png_path = os.path.join(self.dst_dir, "2026_07_23_304.png")
        img_png = Image.new('RGB', (1080, 2400), color='white')
        img_png.save(png_path, 'PNG')

        date_parser = app_main.DateParser()
        meta_png = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=png_path, filename="2026_07_23_304.png", dst_root=self.dst_dir, date_parser=date_parser
        )
        self.assertTrue(meta_png['is_screenshot'])
        self.assertGreaterEqual(meta_png['screenshot_score'], 7)
        self.assertIn("Screenshots", meta_png['target_dir'])

        # 2. 建立真實 1080x2400 JPG 無 EXIF 圖片
        jpg_path = os.path.join(self.dst_dir, "2026_07_23_304.jpg")
        img_jpg = Image.new('RGB', (1080, 2400), color='white')
        img_jpg.save(jpg_path, 'JPEG')

        meta_jpg = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=jpg_path, filename="2026_07_23_304.jpg", dst_root=self.dst_dir, date_parser=date_parser
        )
        self.assertTrue(meta_jpg['is_screenshot'])
        self.assertGreaterEqual(meta_jpg['screenshot_score'], 7)
        self.assertIn("Screenshots", meta_jpg['target_dir'])

        # 3. 普通 LINE 相簿照片 line_album_20230520.jpg ➔ 評分小於 7 (不誤判為截圖)
        meta_line = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=png_path, filename="line_album_20230520.jpg", dst_root=self.dst_dir, date_parser=date_parser
        )
        self.assertFalse(meta_line['is_screenshot'])
        self.assertLess(meta_line['screenshot_score'], 7)

    def test_date_conflict_isolation_with_mock_parser(self):
        """驗證 DateConflict 分支：當 DateParser 回傳 conflict = True 時，目標目錄為 _Review/DateConflict"""
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
        """驗證 LowConfidenceDate 分支：當 confidence < 50 時，目標目錄為 _Review/LowConfidenceDate"""
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

    def test_completed_with_errors_resumption_protection(self):
        """驗證 COMPLETED_WITH_ERRORS 續傳保護：目的檔已存在時不被加入 pending_members 亦不降級"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "resumption_err.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_err_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)

        arc_id = state_mgr.record_archive(job_id, self.zip_path, 100, 1.0, "fp_err")
        media_dest = os.path.join(self.dst_dir, "2018_06_15_001.jpg")
        with open(media_dest, 'wb') as f:
            f.write(self.sample_photo_bytes)

        m = {
            "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp_err",
            "member_index": 0, "member_name": "photo.jpg", "normalized_path": "photo.jpg",
            "filename": "photo.jpg", "member_crc": 100, "uncompressed_size": len(self.sample_photo_bytes),
            "compressed_size": 100, "is_media": True, "is_json": False,
            "status": import_state.TakeoutState.COMPLETED_WITH_ERRORS
        }
        mid = state_mgr.register_member(m)
        state_mgr.update_member_status(mid, import_state.TakeoutState.COMPLETED_WITH_ERRORS, final_destination=media_dest, sha256="abc")

        # 1. 驗證 recover_and_get_pending_members 排除媒體重新解壓
        pending = state_mgr.recover_and_get_pending_members(job_id)
        self.assertEqual(len(pending), 0)

        # 2. 驗證 register_members_batch 重新掃描不會將 COMPLETED_WITH_ERRORS 降級
        m["status"] = import_state.TakeoutState.SECURITY_VALIDATED
        state_mgr.register_members_batch([m])
        self.assertEqual(state_mgr.get_member(mid)['status'], import_state.TakeoutState.COMPLETED_WITH_ERRORS)

        # 3. 驗證 find_existing_sha256_dest 能查到 COMPLETED_WITH_ERRORS 的去重目的檔
        dest_found = state_mgr.find_existing_sha256_dest("abc")
        self.assertEqual(dest_found, media_dest)


if __name__ == '__main__':
    unittest.main()
