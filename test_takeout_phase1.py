# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 1 單元測試
驗證 ZipInfo 安全防護、SQLite 狀態紀錄與跨 ZIP Sidecar 快速盤點
"""

import os
import sys
import shutil
import tempfile
import zipfile
import unittest

sys.path.insert(0, r'C:\Users\chia-hao\Documents\GitHub\Smart-Photo-Organizer')
import import_state
import takeout_zip
import takeout_index


class TestTakeoutPhase1(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.test_dir, "takeout-test-001.zip")
        self.dst_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.dst_dir, exist_ok=True)

        # 建立測試 ZIP 檔
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            # 正常媒體與 JSON
            zf.writestr("Takeout/Google Photos/Album2015/2015_05_12_001.jpg", b"fake photo bytes")
            zf.writestr("Takeout/Google Photos/Album2015/2015_05_12_001.jpg.json", b'{"photoTakenTime":{"timestamp":"1431400000"}}')
            
            # 只有 stem 配對的相片與 JSON
            zf.writestr("Takeout/Google Photos/Album2016/2016_08_20_002.png", b"fake png bytes")
            zf.writestr("Takeout/Google Photos/Album2016/2016_08_20_002.json", b'{"photoTakenTime":{"timestamp":"1471670000"}}')

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_zip_security_validation(self):
        # 測試安全檢查
        bad_info = zipfile.ZipInfo("..\\../etc/passwd")
        is_safe, reason = takeout_zip.TakeoutZipScanner.validate_zip_info(bad_info)
        self.assertFalse(is_safe)
        self.assertIn("路徑穿越", reason)

        abs_info = zipfile.ZipInfo("C:\\Windows\\System32\\cmd.exe")
        is_safe, reason = takeout_zip.TakeoutZipScanner.validate_zip_info(abs_info)
        self.assertFalse(is_safe)
        self.assertIn("磁碟代號", reason)

    def test_phase1_pipeline(self):
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "takeout_import.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "test_job_001"
        state_mgr.create_job(job_id, import_state.JobType.PREVIEW, self.test_dir, self.dst_dir)

        # 掃描與登記
        fingerprint = takeout_zip.TakeoutZipScanner.get_archive_fingerprint(self.zip_path)
        st = os.stat(self.zip_path)
        arc_id = state_mgr.record_archive(job_id, self.zip_path, st.st_size, st.st_mtime, fingerprint)

        members = takeout_zip.TakeoutZipScanner.scan_archive(self.zip_path)
        self.assertEqual(len(members), 4)

        for m in members:
            m['job_id'] = job_id
            m['archive_id'] = arc_id
            m['archive_fingerprint'] = fingerprint
            m['status'] = import_state.TakeoutState.SECURITY_VALIDATED
            state_mgr.register_member(m)

        # 建立索引與配對
        indexer = takeout_index.TakeoutIndexer(state_mgr)
        report = indexer.build_cross_zip_index(job_id)

        self.assertEqual(report['media_count'], 2)
        self.assertEqual(report['json_count'], 2)
        self.assertEqual(report['matched_pair_count'], 2)
        self.assertEqual(report['unmatched_media_count'], 0)


if __name__ == '__main__':
    unittest.main()
