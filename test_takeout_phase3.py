# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 3 單元測試
驗證單向狀態推進 UPSERT、job_type 續傳隔離、EXIF/Metadata 解析、DateParser 決策與 os.rename() 歸檔
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
import takeout_index
import media_metadata


class TestTakeoutPhase3(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.test_dir, "takeout-phase3-test.zip")
        self.dst_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.dst_dir, exist_ok=True)

        self.sample_photo_bytes = b"Fake photo content with EXIF simulation"
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr("Takeout/Google Photos/Album2018/2018_06_15_001.jpg", self.sample_photo_bytes)
            zf.writestr("Takeout/Google Photos/Album2018/2018_06_15_001.jpg.json", b'{"photoTakenTime":{"timestamp":"1529064000"}}')

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_upsert_status_never_downgrades(self):
        """驗證單向狀態推進 UPSERT：重掃描時 VERIFIED 狀態不會降級回 SECURITY_VALIDATED"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "upsert_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_upsert_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)
        arc_id = state_mgr.record_archive(job_id, self.zip_path, 100, 1.0, "fp1")

        m = {
            "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp1",
            "member_index": 0, "member_name": "photo.jpg", "normalized_path": "photo.jpg",
            "filename": "photo.jpg", "member_crc": 100, "uncompressed_size": 200,
            "compressed_size": 150, "is_media": True, "is_json": False,
            "status": import_state.TakeoutState.SECURITY_VALIDATED
        }
        mid = state_mgr.register_member(m)

        # 推進狀態至 VERIFIED
        state_mgr.update_member_status(mid, import_state.TakeoutState.VERIFIED, part_path="dummy.part", sha256="abc")
        m_before = state_mgr.get_member(mid)
        self.assertEqual(m_before['status'], import_state.TakeoutState.VERIFIED)

        # 再次執行 register_members_batch (模擬 Phase 1 重新掃描)
        m["status"] = import_state.TakeoutState.SECURITY_VALIDATED
        state_mgr.register_members_batch([m])

        # 驗證狀態維持 VERIFIED，未降級
        m_after = state_mgr.get_member(mid)
        self.assertEqual(m_after['status'], import_state.TakeoutState.VERIFIED)

    def test_find_resumable_job_filters_job_type(self):
        """驗證 find_resumable_job() 精準過濾 job_type，防止 PREVIEW 與 IMPORT 互相續傳"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "job_type_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)

        fp = takeout_zip.TakeoutZipScanner.get_archive_fingerprint(self.zip_path)

        # 建立 IMPORT 類型的 Job 並設為 CANCELLED
        job_import = "job_import_001"
        state_mgr.create_job(job_import, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)
        state_mgr.record_archive(job_import, self.zip_path, 100, 1.0, fp)
        state_mgr.update_job_status(job_import, import_state.TakeoutState.CANCELLED)

        # 查詢 PREVIEW 類型應回傳 None
        found_prev = state_mgr.find_resumable_job(self.test_dir, self.dst_dir, [fp], job_type=import_state.JobType.PREVIEW)
        self.assertIsNone(found_prev)

        # 查詢 IMPORT 類型應精準找到 job_import
        found_imp = state_mgr.find_resumable_job(self.test_dir, self.dst_dir, [fp], job_type=import_state.JobType.IMPORT)
        self.assertEqual(found_imp, job_import)

    def test_single_item_end_to_end_pipeline_and_rename(self):
        """驗證單一媒體串流解壓 ➔ Metadata 日期決策 ➔ Windows os.rename() 原子更名全流程"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "pipeline_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_pipe_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)
        arc_id = state_mgr.record_archive(job_id, self.zip_path, 100, 1.0, "fp1")

        # 串流解壓
        part_path = os.path.join(self.dst_dir, "_ImportTemp", job_id, "test.part")
        res = takeout_zip.TakeoutZipScanner.extract_member_stream(
            self.zip_path, member_index=0, part_path=part_path
        )
        self.assertTrue(os.path.exists(part_path))

        # 解析 Sidecar JSON
        json_bytes = b'{"photoTakenTime":{"timestamp":"1529064000"}}'
        json_data = media_metadata.MediaMetadataExtractor.parse_sidecar_json_bytes(json_bytes)
        self.assertIsNotNone(json_data)
        self.assertEqual(json_data['timestamp'], 1529064000)

        # 決策日期
        meta_res = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=part_path,
            filename="2018_06_15_001.jpg",
            dst_root=self.dst_dir,
            json_data=json_data
        )

        self.assertEqual(meta_res['date_str'], "2018-06-15")

        # 執行更名歸檔
        target_dir = meta_res['target_dir']
        os.makedirs(target_dir, exist_ok=True)
        final_dest = os.path.join(target_dir, "2018_06_15_001.jpg")
        os.rename(part_path, final_dest)

        # 驗證 .part 已移走，目的檔順利寫入
        self.assertFalse(os.path.exists(part_path))
        self.assertTrue(os.path.exists(final_dest))


if __name__ == '__main__':
    unittest.main()
