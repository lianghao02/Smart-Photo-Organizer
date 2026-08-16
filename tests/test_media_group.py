import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 2 - MediaGroup 單元測試 (test_media_group.py)
驗證 Live Photo (HEIC+MOV) 配對、RAW/JPEG 配對、Sidecar 整合、獨立媒體 MediaGroup 建立、SQLite 持久化與唯讀安全性。
"""

import os
import sqlite3
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import import_state
from source_index import SourceItem
from media_group import MediaGroupBuilder, GroupRole


class TestMediaGroup(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_state.db")
        self.state_mgr = import_state.TakeoutStateManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_live_photo_heic_and_mov_pairing(self):
        """驗證同目錄 HEIC + MOV Live Photo 配對成功，標記相片為 PRIMARY，影片為 LIVE_PHOTO_VIDEO"""
        heic_item = SourceItem("m1", "FOLDER", "Album/IMG_0001.HEIC", "IMG_0001.HEIC", ".heic", 1000, is_media=True, is_json=False)
        mov_item = SourceItem("m2", "FOLDER", "Album/IMG_0001.MOV", "IMG_0001.MOV", ".mov", 5000, is_media=True, is_json=False)

        groups = MediaGroupBuilder.build_groups([heic_item, mov_item])
        self.assertEqual(len(groups), 1)

        mg = groups[0]
        self.assertEqual(mg.status, "PAIRED")
        self.assertEqual(len(mg.members), 2)
        self.assertEqual(mg.primary_media.filename, "IMG_0001.HEIC")

        roles = {m.source_item.filename: m.role for m in mg.members}
        self.assertEqual(roles["IMG_0001.HEIC"], GroupRole.PRIMARY)
        self.assertEqual(roles["IMG_0001.MOV"], GroupRole.LIVE_PHOTO_VIDEO)

    def test_live_photo_pairing_with_sidecar_json(self):
        """驗證 Live Photo 配對群組同時結合 SidecarMatcher 找到的 JSON Sidecar"""
        heic_item = SourceItem("m1", "FOLDER", "Album/IMG_0002.HEIC", "IMG_0002.HEIC", ".heic", 1000, is_media=True, is_json=False)
        mov_item = SourceItem("m2", "FOLDER", "Album/IMG_0002.MOV", "IMG_0002.MOV", ".mov", 5000, is_media=True, is_json=False)
        json_item = SourceItem("j1", "FOLDER", "Album/IMG_0002.HEIC.json", "IMG_0002.HEIC.json", ".json", 200, is_media=False, is_json=True)

        groups = MediaGroupBuilder.build_groups([heic_item, mov_item, json_item])
        self.assertEqual(len(groups), 1)

        mg = groups[0]
        self.assertEqual(len(mg.members), 3)

        roles = {m.source_item.filename: m.role for m in mg.members}
        self.assertEqual(roles["IMG_0002.HEIC"], GroupRole.PRIMARY)
        self.assertEqual(roles["IMG_0002.MOV"], GroupRole.LIVE_PHOTO_VIDEO)
        self.assertEqual(roles["IMG_0002.HEIC.json"], GroupRole.GOOGLE_JSON)

    def test_raw_and_jpeg_pairing(self):
        """驗證 RAW + JPEG (例如 .cr3 + .jpg) 成功配對，RAW 作為 PRIMARY，JPEG 標記為 RAW_PAIR"""
        cr3_item = SourceItem("m1", "FOLDER", "Album/DSC_0001.CR3", "DSC_0001.CR3", ".cr3", 25000, is_media=True, is_json=False)
        jpg_item = SourceItem("m2", "FOLDER", "Album/DSC_0001.JPG", "DSC_0001.JPG", ".jpg", 3000, is_media=True, is_json=False)

        groups = MediaGroupBuilder.build_groups([cr3_item, jpg_item])
        self.assertEqual(len(groups), 1)

        mg = groups[0]
        self.assertEqual(mg.primary_media.filename, "DSC_0001.CR3")

        roles = {m.source_item.filename: m.role for m in mg.members}
        self.assertEqual(roles["DSC_0001.CR3"], GroupRole.PRIMARY)
        self.assertEqual(roles["DSC_0001.JPG"], GroupRole.RAW_PAIR)

    def test_isolated_single_media(self):
        """驗證無關聯之獨立媒體獨立建立單成員 MediaGroup"""
        single_item = SourceItem("m1", "FOLDER", "Album/single.jpg", "single.jpg", ".jpg", 1000, is_media=True, is_json=False)

        groups = MediaGroupBuilder.build_groups([single_item])
        self.assertEqual(len(groups), 1)

        mg = groups[0]
        self.assertEqual(len(mg.members), 1)
        self.assertEqual(mg.members[0].role, GroupRole.PRIMARY)
        self.assertEqual(mg.status, "DISCOVERED")

    def test_state_connection_context_closes_connection(self):
        connection = self.state_mgr._get_conn()
        with connection as active_connection:
            active_connection.execute("SELECT 1")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_sqlite_media_group_persistence(self):
        """驗證 SQLite media_groups 與 media_group_members 資料表寫入與查詢"""
        job_id = "job_media_group_test"
        self.state_mgr.create_job(job_id, "IMPORT", self.test_dir, self.test_dir)
        gid = "mg_test_001"

        members = [
            {"member_id": 101, "source_key": "m1", "role": GroupRole.PRIMARY},
            {"member_id": 102, "source_key": "m2", "role": GroupRole.LIVE_PHOTO_VIDEO},
            {"member_id": 103, "source_key": "j1", "role": GroupRole.GOOGLE_JSON},
        ]

        saved_gid = self.state_mgr.create_media_group(
            group_id=gid,
            job_id=job_id,
            primary_member_id=101,
            source_type="FOLDER",
            status="PAIRED",
            members=members
        )
        self.assertEqual(saved_gid, gid)

        record = self.state_mgr.get_media_group(gid)
        self.assertIsNotNone(record)
        self.assertEqual(record["group_id"], gid)
        self.assertEqual(record["job_id"], job_id)
        self.assertEqual(record["status"], "PAIRED")
        self.assertEqual(len(record["members"]), 3)

        # 同一群組重寫不得累積重複成員。
        self.state_mgr.create_media_group(
            group_id=gid,
            job_id=job_id,
            primary_member_id=101,
            source_type="FOLDER",
            status="PAIRED",
            members=members,
        )
        record = self.state_mgr.get_media_group(gid)
        self.assertEqual(len(record["members"]), 3)

        job_groups = self.state_mgr.list_media_groups(job_id)
        self.assertEqual(len(job_groups), 1)
        self.assertEqual(job_groups[0]["group_id"], gid)

    def test_cross_zip_same_name_media_are_not_paired(self):
        """不同 ZIP 即使邏輯路徑與 stem 相同，也不得誤組為 Live Photo。"""
        heic_item = SourceItem(
            "zip:a:1", "TAKEOUT_ZIP", "Album/IMG_0003.HEIC", "IMG_0003.HEIC",
            ".heic", 1000, True, False, archive_fingerprint="archive-a",
        )
        mov_item = SourceItem(
            "zip:b:1", "TAKEOUT_ZIP", "Album/IMG_0003.MOV", "IMG_0003.MOV",
            ".mov", 5000, True, False, archive_fingerprint="archive-b",
        )

        groups = MediaGroupBuilder.build_groups([heic_item, mov_item])
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(len(group.members) == 1 for group in groups))

    def test_unsupported_same_stem_formats_remain_separate(self):
        """PNG+MKV 與 JPG+PNG 都不是規格中的配對，不得誤綁。"""
        items = [
            SourceItem("m1", "FOLDER", "Album/sample.png", "sample.png", ".png", 100, True, False),
            SourceItem("m2", "FOLDER", "Album/sample.mkv", "sample.mkv", ".mkv", 100, True, False),
            SourceItem("m3", "FOLDER", "Album/still.jpg", "still.jpg", ".jpg", 100, True, False),
            SourceItem("m4", "FOLDER", "Album/still.png", "still.png", ".png", 100, True, False),
        ]

        groups = MediaGroupBuilder.build_groups(items)
        self.assertEqual(len(groups), 4)
        self.assertTrue(all(len(group.members) == 1 for group in groups))

    def test_numbered_stems_do_not_cross_pair(self):
        """IMG 與 IMG(1) 是不同媒體，不可因移除編號而誤配。"""
        heic_item = SourceItem("m1", "FOLDER", "Album/IMG.HEIC", "IMG.HEIC", ".heic", 100, True, False)
        mov_item = SourceItem("m2", "FOLDER", "Album/IMG(1).MOV", "IMG(1).MOV", ".mov", 100, True, False)

        groups = MediaGroupBuilder.build_groups([heic_item, mov_item])
        self.assertEqual(len(groups), 2)

    def test_group_result_is_deterministic(self):
        """輸入順序不得改變主媒體、成員角色或 group_id。"""
        raw_item = SourceItem("m2", "FOLDER", "Album/DSC.RW2", "DSC.RW2", ".rw2", 200, True, False)
        jpg_item = SourceItem("m1", "FOLDER", "Album/DSC.JPG", "DSC.JPG", ".jpg", 100, True, False)

        first = MediaGroupBuilder.build_groups([jpg_item, raw_item])[0]
        second = MediaGroupBuilder.build_groups([raw_item, jpg_item])[0]
        self.assertEqual(first.group_id, second.group_id)
        self.assertEqual(first.primary_media.source_key, "m2")
        self.assertEqual(
            [(member.source_item.source_key, member.role) for member in first.members],
            [(member.source_item.source_key, member.role) for member in second.members],
        )

    def test_group_id_is_scoped_by_job(self):
        """同一來源在不同 Job 中必須取得不同主鍵，避免 SQLite 跨任務覆寫。"""
        item = SourceItem("m1", "FOLDER", "Album/photo.jpg", "photo.jpg", ".jpg", 100, True, False)
        first = MediaGroupBuilder.build_groups([item], job_id="job-a")[0]
        second = MediaGroupBuilder.build_groups([item], job_id="job-b")[0]
        self.assertNotEqual(first.group_id, second.group_id)

    def test_phase2_duplicate_member_migration(self):
        """Phase 2 初版資料庫若已有重複成員，升級時須保留一筆並建立唯一索引。"""
        legacy_db = os.path.join(self.test_dir, "legacy_phase2.db")
        with sqlite3.connect(legacy_db) as conn:
            conn.executescript("""
                CREATE TABLE media_groups (
                    group_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    primary_member_id INTEGER,
                    source_type TEXT NOT NULL,
                    capture_date TEXT,
                    date_source TEXT,
                    date_confidence INTEGER,
                    status TEXT NOT NULL DEFAULT 'DISCOVERED',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE media_group_members (
                    group_member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    member_id INTEGER,
                    source_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO media_groups VALUES (
                    'mg_legacy', 'job_legacy', NULL, 'FOLDER', NULL, NULL, NULL,
                    'DISCOVERED', '2026-01-01T00:00:00'
                );
                INSERT INTO media_group_members
                    (group_id, member_id, source_key, role, created_at)
                VALUES
                    ('mg_legacy', NULL, 'folder:photo.jpg', 'PRIMARY', '2026-01-01T00:00:00'),
                    ('mg_legacy', NULL, 'folder:photo.jpg', 'PRIMARY', '2026-01-01T00:00:01');
            """)

        migrated = import_state.TakeoutStateManager(legacy_db)
        record = migrated.get_media_group("mg_legacy")
        self.assertEqual(len(record["members"]), 1)
        with migrated._get_conn() as conn:
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(media_group_members)")
            }
        self.assertIn("idx_mg_members_unique_source", indexes)

    def test_read_only_verification(self):
        """驗證 Phase 2 建構 MediaGroup 過程中無任何實體檔案被搬移、改名或刪除"""
        src_folder = os.path.join(self.test_dir, "sample_photos")
        os.makedirs(src_folder, exist_ok=True)

        p1 = os.path.join(src_folder, "test.heic")
        p2 = os.path.join(src_folder, "test.mov")
        with open(p1, 'wb') as f: f.write(b"heic content")
        with open(p2, 'wb') as f: f.write(b"mov content")

        heic_item = SourceItem("m1", "FOLDER", "test.heic", "test.heic", ".heic", 12, is_media=True, is_json=False, abs_path=p1)
        mov_item = SourceItem("m2", "FOLDER", "test.mov", "test.mov", ".mov", 11, is_media=True, is_json=False, abs_path=p2)

        groups = MediaGroupBuilder.build_groups([heic_item, mov_item])
        self.assertEqual(len(groups), 1)

        # 斷言實體檔案完好無損
        self.assertTrue(os.path.exists(p1))
        self.assertTrue(os.path.exists(p2))


if __name__ == '__main__':
    unittest.main()
