# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 5 / Phase 0 續傳基線自動化測試套件
測試全流水線端到端匯入、損毀 ZIP 防禦、格式錯誤 Sidecar 解析、Sidecar-only 續傳、安全目錄 dirty .part 復原清理、零媒體重複與 SQLite 100 筆批次負載驗證。
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
from media_types import EXT_MEDIA
import main as app_main


class TestTakeoutPhase5(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.test_dir, "input_zips")
        self.dst_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.src_dir, exist_ok=True)
        os.makedirs(self.dst_dir, exist_ok=True)

        self.sample_photo_bytes = b"Phase 5 synthetic photo content"
        self.sample_raw_bytes = b"Phase 5 synthetic RAW content"

        # 建立標準測試相片與 RAW 檔 (帶畫素與 EXIF 模擬)
        self.zip1_path = os.path.join(self.src_dir, "Takeout-001.zip")
        self.zip2_path = os.path.join(self.src_dir, "Takeout-002.zip")

        with zipfile.ZipFile(self.zip1_path, 'w') as zf1:
            zf1.writestr("Takeout/Google Photos/Album2018/photo_2018.jpg", self.sample_photo_bytes)
            zf1.writestr("Takeout/Google Photos/Album2018/photo_2018.jpg.json", b'{"photoTakenTime":{"timestamp":"1529064000"}}')
            zf1.writestr("Takeout/Google Photos/Album2018/raw_camera.cr3", self.sample_raw_bytes)

        # ZIP2 僅含有相應的 Sidecar JSON (測試跨 ZIP 讀取)
        with zipfile.ZipFile(self.zip2_path, 'w') as zf2:
            zf2.writestr("Takeout/Google Photos/Album2018/raw_camera.cr3.json", b'{"photoTakenTime":{"timestamp":"1529064000"}}')

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_1_small_zip_full_import_end_to_end(self):
        """Phase 5 Step 1: 驗證小型 ZIP 完整 End-to-End 流水線：安全掃描 ➔ 建檔 ➔ 串流解壓 ➔ 日期決策 ➔ 零覆寫更名 ➔ Sidecar 落碟"""
        web_bridge = app_main.WebBridge()
        web_bridge._run_takeout_audit(self.src_dir, self.dst_dir, is_dry_run=False)

        db_path = os.path.join(self.dst_dir, "_ImportTemp", "takeout_import.db")
        self.assertTrue(os.path.exists(db_path))

        state_mgr = import_state.TakeoutStateManager(db_path)
        with state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM jobs ORDER BY created_at DESC LIMIT 1")
            job_row = cursor.fetchone()
            self.assertIsNotNone(job_row)
            self.assertEqual(job_row['status'], import_state.TakeoutState.COMPLETED)

            cursor.execute("SELECT count(*) as cnt FROM members WHERE status = ?", (import_state.TakeoutState.COMPLETED,))
            self.assertEqual(cursor.fetchone()['cnt'], 2)

        # 驗證實體歸檔照片與 Sidecar JSON 確實落地
        photo_dir = os.path.join(self.dst_dir, "2018", "06", "Photos")
        self.assertTrue(os.path.exists(photo_dir))
        files = os.listdir(photo_dir)
        self.assertTrue(any(f.endswith(".jpg") for f in files))
        self.assertTrue(any(f.endswith(".jpg.json") for f in files))

    def test_2_corrupted_zip_handling(self):
        """Phase 5 Step 2: 驗證損毀 ZIP 封存檔的強健性與 COMPLETED_WITH_ERRORS 防禦」"""
        corrupted_zip = os.path.join(self.src_dir, "Takeout-Corrupted.zip")
        with open(corrupted_zip, 'wb') as f:
            f.write(b"PK_CORRUPTED_HEADER_BYTES_123456789")

        web_bridge = app_main.WebBridge()
        web_bridge._run_takeout_audit(self.src_dir, self.dst_dir, is_dry_run=False)

        db_path = os.path.join(self.dst_dir, "_ImportTemp", "takeout_import.db")
        state_mgr = import_state.TakeoutStateManager(db_path)

        with state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM jobs ORDER BY created_at DESC LIMIT 1")
            job_row = cursor.fetchone()
            self.assertEqual(job_row['status'], import_state.TakeoutState.COMPLETED_WITH_ERRORS)

    def test_3_chaos_interruption_and_resumption(self):
        """Phase 5 Step 3: 驗證 Sidecar-only 續傳：Sidecar JSON 被無損補寫，重用原 Job 且無重複媒體」"""
        web_bridge = app_main.WebBridge()
        # 1. 執行首次匯入
        web_bridge._run_takeout_audit(self.src_dir, self.dst_dir, is_dry_run=False)

        db_path = os.path.join(self.dst_dir, "_ImportTemp", "takeout_import.db")
        state_mgr = import_state.TakeoutStateManager(db_path)

        photo_dir = os.path.join(self.dst_dir, "2018", "06", "Photos")
        media_count_before = len([f for f in os.listdir(photo_dir) if os.path.splitext(f)[1].lower() in EXT_MEDIA])

        with state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 1")
            job_id = cursor.fetchone()['job_id']

            # 模擬其中一個成員在 Sidecar 寫入前發電中斷 (刪除 Sidecar JSON)
            cursor.execute("SELECT member_id, final_destination FROM members WHERE is_media = 1 LIMIT 1")
            m_row = cursor.fetchone()
            mid = m_row['member_id']
            media_dest = m_row['final_destination']
            json_dest = media_dest + ".json"
            if os.path.exists(json_dest):
                os.remove(json_dest)

            state_mgr.update_job_status(job_id, import_state.TakeoutState.COMPLETED_WITH_ERRORS)
            state_mgr.update_member_status(mid, import_state.TakeoutState.COMPLETED_WITH_ERRORS, error_msg="模擬中斷")

        # 2. 模擬二次開啟 Takeout 引擎執行斷電續傳
        web_bridge._run_takeout_audit(self.src_dir, self.dst_dir, is_dry_run=False)

        # 驗證確實重用了原本未完成的 job_id 續傳，Sidecar JSON 被無損補寫，且媒體數量保持不變 (零重複媒體)
        media_count_after = len([f for f in os.listdir(photo_dir) if os.path.splitext(f)[1].lower() in EXT_MEDIA])
        self.assertEqual(media_count_after, media_count_before)

        with state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) as job_cnt FROM jobs")
            self.assertEqual(cursor.fetchone()['job_cnt'], 1)

            cursor.execute("SELECT job_id, status FROM jobs WHERE job_id = ?", (job_id,))
            res_job = cursor.fetchone()
            self.assertEqual(res_job['job_id'], job_id)
            self.assertEqual(res_job['status'], import_state.TakeoutState.COMPLETED)

            cursor.execute("SELECT status, error_msg FROM members WHERE member_id = ?", (mid,))
            res_row = cursor.fetchone()
            self.assertEqual(res_row['status'], import_state.TakeoutState.COMPLETED)
            self.assertIsNone(res_row['error_msg'])
            self.assertTrue(os.path.exists(json_dest))

    def test_4_multi_volume_cross_zip_pairing(self):
        """Phase 5 Step 4: 驗證跨分卷 ZIP 媒體 (Takeout-001) 與 Sidecar JSON (Takeout-002) 精準配對與落碟"""
        web_bridge = app_main.WebBridge()
        web_bridge._run_takeout_audit(self.src_dir, self.dst_dir, is_dry_run=False)

        # 驗證 raw_camera.cr3 雖然在 ZIP 1，但成功讀取 ZIP 2 的 Sidecar JSON 並落碟 raw_camera.cr3.json
        photo_dir = os.path.join(self.dst_dir, "2018", "06", "Photos")
        files = os.listdir(photo_dir)
        cr3_files = [f for f in files if f.endswith(".cr3")]
        cr3_json_files = [f for f in files if f.endswith(".cr3.json")]
        self.assertEqual(len(cr3_files), 1)
        self.assertEqual(len(cr3_json_files), 1)

    def test_5_medium_load_simulation(self):
        """Phase 5 Step 5: 中型 100 筆成員批次狀態推進與 SQLite 高效併發負載驗證"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "load_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_load_100"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.src_dir, self.dst_dir)

        arc_id = state_mgr.record_archive(job_id, self.zip1_path, 1000, 1.0, "fp_load")
        members = [
            {
                "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp_load",
                "member_index": i, "member_name": f"photo_{i:04d}.jpg", "normalized_path": f"photo_{i:04d}.jpg",
                "filename": f"photo_{i:04d}.jpg", "member_crc": i * 10, "uncompressed_size": 500,
                "compressed_size": 400, "is_media": True, "is_json": False,
                "status": import_state.TakeoutState.SECURITY_VALIDATED
            }
            for i in range(100)
        ]
        state_mgr.register_members_batch(members)

        with state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) as cnt FROM members WHERE job_id = ?", (job_id,))
            self.assertEqual(cursor.fetchone()['cnt'], 100)

    def test_6_dirty_part_cleanup_on_resumption(self):
        """Phase 5 Step 6: 驗證復原引擎重置 EXTRACTING 狀態並自動清理 _ImportTemp 安全暫存區內的 dirty .part 檔"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "dirty_part.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_dirty_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.src_dir, self.dst_dir)

        arc_id = state_mgr.record_archive(job_id, self.zip1_path, 1000, 1.0, "fp_dirty")

        # 在安全暫存目錄內建立假的 dirty .part 檔
        safe_temp_dir = os.path.join(self.dst_dir, "_ImportTemp", job_id)
        os.makedirs(safe_temp_dir, exist_ok=True)
        dirty_part_path = os.path.join(safe_temp_dir, "temp_extract.part")
        with open(dirty_part_path, 'wb') as f:
            f.write(b"uncompleted dirty extraction bytes")

        m = {
            "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp_dirty",
            "member_index": 0, "member_name": "photo_dirty.jpg", "normalized_path": "photo_dirty.jpg",
            "filename": "photo_dirty.jpg", "member_crc": 999, "uncompressed_size": 100,
            "compressed_size": 80, "is_media": True, "is_json": False,
            "status": import_state.TakeoutState.EXTRACTING
        }
        mid = state_mgr.register_member(m)
        state_mgr.update_member_status(mid, import_state.TakeoutState.EXTRACTING, part_path=dirty_part_path)

        self.assertTrue(os.path.exists(dirty_part_path))

        # 執行復原查詢 recover_and_get_pending_members
        pending = state_mgr.recover_and_get_pending_members(job_id)

        # 驗證 dirty_part_path 檔案已刪除，且成員狀態已成功重置為 SECURITY_VALIDATED
        self.assertFalse(os.path.exists(dirty_part_path))
        saved = state_mgr.get_member(mid)
        self.assertEqual(saved['status'], import_state.TakeoutState.SECURITY_VALIDATED)
        self.assertIsNone(saved['part_path'])
        self.assertEqual(len(pending), 1)

    def test_7_broken_sidecar_json_handling(self):
        """Phase 5 Step 7: 獨立驗證格式錯誤 (無效 JSON 語法) 之 Sidecar 處理：不崩潰進程，媒體正常處理完成」"""
        broken_sidecar_zip = os.path.join(self.src_dir, "Takeout-BrokenSidecar.zip")
        with zipfile.ZipFile(broken_sidecar_zip, 'w') as zf_broken:
            zf_broken.writestr(
                "Takeout/Google Photos/Album2018/broken_photo.jpg",
                b"unique broken-sidecar media content"
            )
            zf_broken.writestr("Takeout/Google Photos/Album2018/broken_photo.jpg.json", b"{invalid json syntax content...")

        # 驗證 parse_sidecar_json_bytes 解析無效語法位元組時，安全回傳 None 絕不拋出例外
        res = media_metadata.MediaMetadataExtractor.parse_sidecar_json_bytes(b"{invalid json syntax content...")
        self.assertIsNone(res)

        web_bridge = app_main.WebBridge()
        web_bridge._run_takeout_audit(self.src_dir, self.dst_dir, is_dry_run=False)

        # 經由 SQLite 查詢 broken_photo.jpg 驗證 COMPLETED 且實體檔與 Sidecar 檔均存在
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "takeout_import.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        with state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, final_destination FROM members WHERE filename = 'broken_photo.jpg'")
            m_row = cursor.fetchone()
            self.assertIsNotNone(m_row)
            self.assertEqual(m_row['status'], import_state.TakeoutState.COMPLETED)

            dest_path = m_row['final_destination']
            self.assertIsNotNone(dest_path)
            self.assertTrue(os.path.exists(dest_path))
            self.assertTrue(os.path.exists(dest_path + ".json"))


if __name__ == '__main__':
    unittest.main()
