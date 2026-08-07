# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 1.3 阻斷修補與相容性測試
驗證 Schema 遷移 (Migration)、截斷 supplemental metadata、JSON 獨佔指派與 DB UPSERT。
"""

import os
import sys
import shutil
import sqlite3
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

        # 建立測試 ZIP 檔 (含 截斷 supplemental-metadata.json 與 PNG stem 配對)
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            # 1. 正常全名配對
            zf.writestr("Takeout/Google Photos/Album2015/2015_05_12_001.jpg", b"fake photo bytes")
            zf.writestr("Takeout/Google Photos/Album2015/2015_05_12_001.jpg.json", b'{"photoTakenTime":{"timestamp":"1431400000"}}')
            
            # 2. PNG 與只有 stem 的 JSON 配對 (IMG_001.png 匹配 IMG_001.json)
            zf.writestr("Takeout/Google Photos/Album2016/IMG_001.png", b"fake png bytes")
            zf.writestr("Takeout/Google Photos/Album2016/IMG_001.json", b'{"photoTakenTime":{"timestamp":"1471670000"}}')

            # 3. 截斷的 Supplemental metadata 配對 (IMG_002.HEIC 匹配 IMG_002.HEIC.supplemental-metada.json)
            zf.writestr("Takeout/Google Photos/Album2017/IMG_002.HEIC", b"fake heic bytes")
            zf.writestr("Takeout/Google Photos/Album2017/IMG_002.HEIC.supplemental-metada.json", b'{"photoTakenTime":{"timestamp":"1500000000"}}')

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_db_migration_from_full_old_schema(self):
        """驗證完整 Phase 1 舊版三張資料表開啟時，自動遷移與 UNIQUE 索引及 UPSERT 均正常升級"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "full_old_takeout.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # 建立完整舊版 Phase 1 三張資料表 (缺少 status/error_msg 與 UNIQUE 約束)
        conn = sqlite3.connect(db_path)
        conn.execute("""
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            src_dir TEXT NOT NULL,
            dst_dir TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL
        );
        """)
        conn.execute("""
        CREATE TABLE archives (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            archive_path TEXT NOT NULL,
            archive_size INTEGER NOT NULL,
            archive_mtime REAL NOT NULL,
            fingerprint TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        conn.execute("""
        CREATE TABLE members (
            member_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            archive_id INTEGER NOT NULL,
            archive_fingerprint TEXT NOT NULL,
            member_index INTEGER NOT NULL,
            member_name TEXT NOT NULL,
            normalized_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            member_crc INTEGER NOT NULL,
            uncompressed_size INTEGER NOT NULL,
            compressed_size INTEGER NOT NULL,
            is_media INTEGER NOT NULL,
            is_json INTEGER NOT NULL,
            status TEXT NOT NULL,
            part_path TEXT,
            sha256 TEXT,
            date_candidate TEXT,
            date_source TEXT,
            date_confidence INTEGER,
            dest_reserved TEXT,
            final_destination TEXT,
            error_msg TEXT,
            updated_at TEXT NOT NULL
        );
        """)
        conn.execute("""
        CREATE TABLE sidecar_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            media_member_id INTEGER NOT NULL,
            json_member_id INTEGER NOT NULL,
            match_quality TEXT NOT NULL
        );
        """)
        conn.commit()
        conn.close()

        # 使用 TakeoutStateManager 開啟該舊資料庫，驗證 Migration 是否成功
        state_mgr = import_state.TakeoutStateManager(db_path)
        with state_mgr._get_conn() as c:
            cursor = c.cursor()
            cursor.execute("PRAGMA table_info(archives);")
            cols = {r['name'] for r in cursor.fetchall()}
            self.assertIn("status", cols)
            self.assertIn("error_msg", cols)

        # 測試在遷移後的資料庫中執行 UPSERT 註冊
        m_item = {
            "job_id": "j1", "archive_id": 1, "archive_fingerprint": "fp1",
            "member_index": 0, "member_name": "test.jpg", "normalized_path": "test.jpg",
            "filename": "test.jpg", "member_crc": 123, "uncompressed_size": 100,
            "compressed_size": 80, "is_media": True, "is_json": False, "status": "VALIDATED"
        }
        state_mgr.register_members_batch([m_item])
        # 重複插入同一個 (archive_id, member_index)
        m_item["status"] = "UPDATED"
        state_mgr.register_members_batch([m_item])
        
        m_res = state_mgr.get_member(1)
        self.assertIsNotNone(m_res)
        self.assertEqual(m_res['status'], "UPDATED")

    def test_zip_security_validation(self):
        # 測試路徑穿越檢查
        bad_info = zipfile.ZipInfo("..\\../etc/passwd")
        is_safe, reason = takeout_zip.TakeoutZipScanner.validate_zip_info(bad_info)
        self.assertFalse(is_safe)
        self.assertIn("路徑穿越", reason)

        # 測試磁碟代號檢查
        abs_info = zipfile.ZipInfo("C:\\Windows\\System32\\cmd.exe")
        is_safe, reason = takeout_zip.TakeoutZipScanner.validate_zip_info(abs_info)
        self.assertFalse(is_safe)
        self.assertIn("磁碟代號", reason)

        # 測試符號連結檢查
        sym_info = zipfile.ZipInfo("symlink_file")
        sym_info.external_attr = 0o120000 << 16
        is_safe, reason = takeout_zip.TakeoutZipScanner.validate_zip_info(sym_info)
        self.assertFalse(is_safe)
        self.assertIn("符號連結", reason)

        # 測試非空零壓縮大小檢查
        zero_info = zipfile.ZipInfo("broken_file.jpg")
        zero_info.file_size = 2000000
        zero_info.compress_size = 0
        is_safe, reason = takeout_zip.TakeoutZipScanner.validate_zip_info(zero_info)
        self.assertFalse(is_safe)
        self.assertIn("壓縮大小為 0", reason)

    def test_phase1_pipeline_with_truncated_supplemental_and_stem(self):
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "takeout_import.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "test_job_001"
        state_mgr.create_job(job_id, import_state.JobType.PREVIEW, self.test_dir, self.dst_dir)

        fingerprint = takeout_zip.TakeoutZipScanner.get_archive_fingerprint(self.zip_path)
        st = os.stat(self.zip_path)
        arc_id = state_mgr.record_archive(job_id, self.zip_path, st.st_size, st.st_mtime, fingerprint)

        members = takeout_zip.TakeoutZipScanner.scan_archive(self.zip_path)
        self.assertEqual(len(members), 6)

        for m in members:
            m['job_id'] = job_id
            m['archive_id'] = arc_id
            m['archive_fingerprint'] = fingerprint
            m['status'] = import_state.TakeoutState.SECURITY_VALIDATED

        state_mgr.register_members_batch(members)

        # 建立索引與配對
        indexer = takeout_index.TakeoutIndexer(state_mgr)
        report = indexer.build_cross_zip_index(job_id)

        self.assertEqual(report['media_count'], 3)
        self.assertEqual(report['json_count'], 3)
        self.assertEqual(report['matched_pair_count'], 3)
        self.assertEqual(report['unmatched_media_count'], 0)
        self.assertEqual(report['unmatched_json_count'], 0)


if __name__ == '__main__':
    unittest.main()
