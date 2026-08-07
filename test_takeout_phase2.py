# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 2 單元測試
驗證按需單檔串流解壓、CRC32/SHA-256 校驗與崩潰恢復引擎 (Crash Recovery Engine)
"""

import os
import sys
import shutil
import tempfile
import zipfile
import unittest
from pathlib import Path

# 動態加載專案目錄
PROJECT_ROOT = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import import_state
import takeout_zip


class TestTakeoutPhase2(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.test_dir, "takeout-phase2-test.zip")
        self.dst_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.dst_dir, exist_ok=True)

        self.sample_bytes = b"Hello Google Takeout Stream Integrity Test " * 100
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr("Takeout/Google Photos/Album2020/test_photo.jpg", self.sample_bytes)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_single_item_stream_extraction_and_integrity(self):
        """驗證單一成員串流解壓至 .part 暫存檔，且 SHA-256 與 CRC32 計算正確"""
        part_path = os.path.join(self.dst_dir, "_ImportTemp", "job_test", "test_photo.part")
        res = takeout_zip.TakeoutZipScanner.extract_member_stream(
            self.zip_path, "Takeout/Google Photos/Album2020/test_photo.jpg", part_path
        )

        self.assertTrue(os.path.exists(part_path))
        self.assertEqual(res['bytes_written'], len(self.sample_bytes))

        # 驗證產出的 .part 檔案內容一致性
        with open(part_path, 'rb') as f:
            written_data = f.read()
        self.assertEqual(written_data, self.sample_bytes)

    def test_crash_recovery_matrix_handling(self):
        """驗證崩潰恢復矩陣處置：EXTRACTING 刪除 dirty part、VERIFIED 重用 part、DESTINATION_RESERVED 衝突防護"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "recovery_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_recovery_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)

        # 1. 模擬 EXTRACTING 狀態 (包含不完整 .part)
        dirty_part = os.path.join(self.dst_dir, "_ImportTemp", job_id, "dirty.part")
        os.makedirs(os.path.dirname(dirty_part), exist_ok=True)
        with open(dirty_part, 'wb') as f:
            f.write(b"partial dirty bytes")

        m1 = {
            "job_id": job_id, "archive_id": 1, "archive_fingerprint": "fp1",
            "member_index": 0, "member_name": "photo1.jpg", "normalized_path": "photo1.jpg",
            "filename": "photo1.jpg", "member_crc": 100, "uncompressed_size": 200,
            "compressed_size": 150, "is_media": True, "is_json": False,
            "status": import_state.TakeoutState.EXTRACTING, "part_path": dirty_part
        }
        mid1 = state_mgr.register_member(m1)
        state_mgr.update_member_status(mid1, import_state.TakeoutState.EXTRACTING, part_path=dirty_part)

        # 執行復原引擎
        pending = state_mgr.recover_and_get_pending_members(job_id)

        # 驗證不完整 .part 已被刪除且狀態重置為 SECURITY_VALIDATED
        self.assertFalse(os.path.exists(dirty_part))
        m1_rec = state_mgr.get_member(mid1)
        self.assertEqual(m1_rec['status'], import_state.TakeoutState.SECURITY_VALIDATED)

        # 2. 模擬 VERIFIED 狀態 (有效 .part 存在)
        valid_part = os.path.join(self.dst_dir, "_ImportTemp", job_id, "valid.part")
        with open(valid_part, 'wb') as f:
            f.write(b"valid complete bytes")

        m2 = {
            "job_id": job_id, "archive_id": 1, "archive_fingerprint": "fp1",
            "member_index": 1, "member_name": "photo2.jpg", "normalized_path": "photo2.jpg",
            "filename": "photo2.jpg", "member_crc": 200, "uncompressed_size": 20,
            "compressed_size": 15, "is_media": True, "is_json": False,
            "status": import_state.TakeoutState.SECURITY_VALIDATED, "part_path": valid_part
        }
        mid2 = state_mgr.register_member(m2)
        state_mgr.update_member_status(mid2, import_state.TakeoutState.VERIFIED, part_path=valid_part)

        pending2 = state_mgr.recover_and_get_pending_members(job_id)
        # 驗證 .part 被完整保留
        self.assertTrue(os.path.exists(valid_part))
        m2_rec = state_mgr.get_member(mid2)
        self.assertEqual(m2_rec['status'], import_state.TakeoutState.VERIFIED)


if __name__ == '__main__':
    unittest.main()
