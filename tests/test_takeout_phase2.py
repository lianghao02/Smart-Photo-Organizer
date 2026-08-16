# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 2.2 阻斷修補單元測試
驗證 commonpath 邊界防禦、Job 續傳檢索、ZipInfo 雙重校驗與崩潰恢復引擎 (Crash Recovery Engine)
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

        self.sample_bytes1 = b"FIRST MEMBER CONTENT " * 50
        self.sample_bytes2 = b"SECOND MEMBER CONTENT " * 50

        # 建立包含同名媒體檔 (same.jpg) 的 ZIP
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr("Album1/same.jpg", self.sample_bytes1)
            zf.writestr("Album2/same.jpg", self.sample_bytes2)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_single_item_stream_extraction_by_member_index(self):
        """驗證依 member_index 精準解壓，避免 ZIP 內部同名檔檔名混淆"""
        part_path1 = os.path.join(self.dst_dir, "_ImportTemp", "job_test", "same1.part")
        res1 = takeout_zip.TakeoutZipScanner.extract_member_stream(
            self.zip_path, member_index=0, part_path=part_path1, expected_filename="Album1/same.jpg"
        )
        self.assertTrue(os.path.exists(part_path1))
        with open(part_path1, 'rb') as f:
            self.assertEqual(f.read(), self.sample_bytes1)

        part_path2 = os.path.join(self.dst_dir, "_ImportTemp", "job_test", "same2.part")
        res2 = takeout_zip.TakeoutZipScanner.extract_member_stream(
            self.zip_path, member_index=1, part_path=part_path2, expected_filename="Album2/same.jpg"
        )
        self.assertTrue(os.path.exists(part_path2))
        with open(part_path2, 'rb') as f:
            self.assertEqual(f.read(), self.sample_bytes2)

    def test_boundary_path_security_prevents_unauthorized_deletion(self):
        """驗證使用 commonpath 嚴格比對，_ImportTemp_evil 等同名前綴目錄或邊界外檔案絕不被刪除"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "boundary_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_boundary_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)

        # 建立看似類似同名前綴的邪惡目錄檔 _ImportTemp_evil/victim.part
        evil_dir = os.path.join(self.dst_dir, "_ImportTemp_evil")
        os.makedirs(evil_dir, exist_ok=True)
        evil_file = os.path.join(evil_dir, "victim.part")
        with open(evil_file, 'w', encoding='utf-8') as f:
            f.write("PROTECTED EVIL FILE")

        # 驗證 _is_safe_part_path 判定為不安全
        self.assertFalse(state_mgr._is_safe_part_path(job_id, evil_file))

        arc_id = state_mgr.record_archive(job_id, self.zip_path, 100, 1.0, "fp1")
        m = {
            "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp1",
            "member_index": 0, "member_name": "photo.jpg", "normalized_path": "photo.jpg",
            "filename": "photo.jpg", "member_crc": 100, "uncompressed_size": 200,
            "compressed_size": 150, "is_media": True, "is_json": False,
            "status": import_state.TakeoutState.EXTRACTING, "part_path": evil_file
        }
        mid = state_mgr.register_member(m)
        state_mgr.update_member_status(mid, import_state.TakeoutState.EXTRACTING, part_path=evil_file)

        # 執行復原引擎
        pending = state_mgr.recover_and_get_pending_members(job_id)

        # 驗證邪惡目錄下的檔案被保護未被刪除
        self.assertTrue(os.path.exists(evil_file))

    def test_find_resumable_job_resumes_uncompleted_task(self):
        """驗證 find_resumable_job 能根據 src, dst 與指紋清單正確比對歷史未完成 Job"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "resumable_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_hist_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)
        fp = takeout_zip.TakeoutZipScanner.get_archive_fingerprint(self.zip_path)
        state_mgr.record_archive(job_id, self.zip_path, 100, 1.0, fp)
        state_mgr.update_job_status(job_id, import_state.TakeoutState.FAILED)

        # 比對尋找
        found_job_id = state_mgr.find_resumable_job(self.test_dir, self.dst_dir, [fp])
        self.assertEqual(found_job_id, job_id)

    def test_crash_recovery_matrix_handling_with_fk(self):
        """驗證外鍵完全寫入條件下的崩潰恢復矩陣處置"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "recovery_fk_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_recovery_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)
        arc_id = state_mgr.record_archive(job_id, self.zip_path, 100, 1.0, "fp1")

        # 1. 模擬 EXTRACTING 狀態 (包含不完整 .part)
        dirty_part = os.path.join(self.dst_dir, "_ImportTemp", job_id, "dirty.part")
        os.makedirs(os.path.dirname(dirty_part), exist_ok=True)
        with open(dirty_part, 'wb') as f:
            f.write(b"partial dirty bytes")

        m1 = {
            "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp1",
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
            "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp1",
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
