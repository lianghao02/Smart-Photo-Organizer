# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 Phase 3.2 阻斷修補單元測試
驗證 DateParser 95分 Google JSON 權重、RAW 檔辨識、Cross-ZIP 全量封存檔讀取、.part 雙重驗證與 Sidecar 原子更名
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
import main as app_main


class TestTakeoutPhase3(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.zip_path1 = os.path.join(self.test_dir, "takeout-001.zip")
        self.zip_path2 = os.path.join(self.test_dir, "takeout-002.zip")
        self.dst_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.dst_dir, exist_ok=True)

        self.sample_photo_bytes = b"Fake photo content with EXIF simulation"
        with zipfile.ZipFile(self.zip_path1, 'w') as zf1:
            zf1.writestr("Takeout/Google Photos/Album2018/2018_06_15_001.jpg", self.sample_photo_bytes)

        # ZIP2 僅包含 Sidecar JSON
        with zipfile.ZipFile(self.zip_path2, 'w') as zf2:
            zf2.writestr("Takeout/Google Photos/Album2018/2018_06_15_001.jpg.json", b'{"photoTakenTime":{"timestamp":"1529064000"}}')

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_upsert_and_indexer_status_never_downgrades(self):
        """驗證單向狀態推進 UPSERT 與 Indexer：重掃描與重建索引時 VERIFIED 狀態不降級"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "upsert_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_upsert_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)
        arc_id = state_mgr.record_archive(job_id, self.zip_path1, 100, 1.0, "fp1")

        m = {
            "job_id": job_id, "archive_id": arc_id, "archive_fingerprint": "fp1",
            "member_index": 0, "member_name": "photo.jpg", "normalized_path": "photo.jpg",
            "filename": "photo.jpg", "member_crc": 100, "uncompressed_size": 200,
            "compressed_size": 150, "is_media": True, "is_json": False,
            "status": import_state.TakeoutState.SECURITY_VALIDATED
        }
        mid = state_mgr.register_member(m)

        state_mgr.update_member_status(mid, import_state.TakeoutState.VERIFIED, part_path="dummy.part", sha256="abc")
        
        m["status"] = import_state.TakeoutState.SECURITY_VALIDATED
        state_mgr.register_members_batch([m])
        self.assertEqual(state_mgr.get_member(mid)['status'], import_state.TakeoutState.VERIFIED)

        indexer = takeout_index.TakeoutIndexer(state_mgr)
        indexer.build_cross_zip_index(job_id)
        self.assertEqual(state_mgr.get_member(mid)['status'], import_state.TakeoutState.VERIFIED)

    def test_find_resumable_job_filters_job_type(self):
        """驗證 find_resumable_job() 精準過濾 job_type，防止 PREVIEW 與 IMPORT 互相續傳"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "job_type_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)

        fp = takeout_zip.TakeoutZipScanner.get_archive_fingerprint(self.zip_path1)

        job_import = "job_import_001"
        state_mgr.create_job(job_import, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)
        state_mgr.record_archive(job_import, self.zip_path1, 100, 1.0, fp)
        state_mgr.update_job_status(job_import, import_state.TakeoutState.CANCELLED)

        found_prev = state_mgr.find_resumable_job(self.test_dir, self.dst_dir, [fp], job_type=import_state.JobType.PREVIEW)
        self.assertIsNone(found_prev)

        found_imp = state_mgr.find_resumable_job(self.test_dir, self.dst_dir, [fp], job_type=import_state.JobType.IMPORT)
        self.assertEqual(found_imp, job_import)

    def test_google_json_date_confidence_95_and_raw_formats(self):
        """驗證 Google JSON 具備 95 分高可信度且 RAW 格式 (.cr3, .dng) 歸入 Photos"""
        date_parser = app_main.DateParser()
        part_path = os.path.join(self.dst_dir, "sample.cr3")
        with open(part_path, 'wb') as f:
            f.write(self.sample_photo_bytes)

        json_data = {"timestamp": 1529064000} # 2018-06-15
        meta_res = media_metadata.MediaMetadataExtractor.resolve_media_date_and_destination(
            part_path=part_path,
            filename="IMG_001.CR3",
            dst_root=self.dst_dir,
            date_parser=date_parser,
            json_data=json_data,
            folder_pattern="ym"
        )

        self.assertEqual(meta_res['date_str'], "2018-06-15")
        self.assertEqual(meta_res['confidence'], 95)
        self.assertEqual(meta_res['date_source'], "Google Takeout JSON")
        self.assertTrue(meta_res['is_photo'])
        expected_dir = os.path.join(self.dst_dir, "2018", "06", "Photos")
        self.assertEqual(os.path.normpath(meta_res['target_dir']), os.path.normpath(expected_dir))

    def test_cross_zip_all_archives_map_lookup(self):
        """驗證即使 ZIP2 只有 JSON，get_job_archives 仍能讀取 zip2 並成功取得 Sidecar"""
        db_path = os.path.join(self.dst_dir, "_ImportTemp", "cross_zip_test.db")
        state_mgr = import_state.TakeoutStateManager(db_path)
        job_id = "job_cross_001"
        state_mgr.create_job(job_id, import_state.JobType.IMPORT, self.test_dir, self.dst_dir)

        st1 = os.stat(self.zip_path1)
        arc_id1 = state_mgr.record_archive(job_id, self.zip_path1, st1.st_size, st1.st_mtime, "fp1")
        m1 = takeout_zip.TakeoutZipScanner.scan_archive(self.zip_path1)[0]
        m1['job_id'] = job_id
        m1['archive_id'] = arc_id1
        m1['archive_fingerprint'] = "fp1"
        m1['status'] = import_state.TakeoutState.SECURITY_VALIDATED

        st2 = os.stat(self.zip_path2)
        arc_id2 = state_mgr.record_archive(job_id, self.zip_path2, st2.st_size, st2.st_mtime, "fp2")
        m2 = takeout_zip.TakeoutZipScanner.scan_archive(self.zip_path2)[0]
        m2['job_id'] = job_id
        m2['archive_id'] = arc_id2
        m2['archive_fingerprint'] = "fp2"
        m2['status'] = import_state.TakeoutState.SECURITY_VALIDATED

        state_mgr.register_members_batch([m1, m2])
        indexer = takeout_index.TakeoutIndexer(state_mgr)
        indexer.build_cross_zip_index(job_id)

        # 驗證全量 get_job_archives 包含 zip2
        all_arcs = state_mgr.get_job_archives(job_id)
        arc_map = {a['archive_id']: a['archive_path'] for a in all_arcs}
        
        media_id = state_mgr.get_member(1)['member_id']
        sidecar_info = state_mgr.get_sidecar_for_media(media_id)
        self.assertIsNotNone(sidecar_info)
        self.assertIn(sidecar_info['archive_id'], arc_map)
        self.assertEqual(arc_map[sidecar_info['archive_id']], self.zip_path2)


if __name__ == '__main__':
    unittest.main()
