# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 1 - 來源索引單元測試 (test_source_index.py)
驗證 FolderSourceIndexer 與 TakeoutSourceIndexer 之唯讀索引、中文路徑、管理目錄排除、Symlink/Junction/Reparse Point 跳過與 ZipInfo 唯讀存取。
"""

import os
import sys
import shutil
import tempfile
import zipfile
import unittest
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from source_index import FolderSourceIndexer, TakeoutSourceIndexer, SourceItem, is_reparse_point_or_link
from takeout_zip import TakeoutZipScanner, ZipSecurityError


class TestSourceIndex(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.folder_dir = os.path.join(self.test_dir, "test_folder_src")
        os.makedirs(self.folder_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_folder_source_indexer_unicode_and_management_dir_exclusion(self):
        """驗證一般資料夾唯讀索引：中文/Unicode 路徑正確建立，專案管理目錄 (_Review, _Quarantine 等) 成功排除"""
        # 1. 建立正常相片與 Sidecar (包含中文與 Unicode 檔名)
        normal_sub = os.path.join(self.folder_dir, "2018年家庭旅遊")
        os.makedirs(normal_sub, exist_ok=True)

        photo_path = os.path.join(normal_sub, "台北101照片.jpg")
        json_path = os.path.join(normal_sub, "台北101照片.jpg.json")
        with open(photo_path, 'wb') as f:
            f.write(b"sample photo content")
        with open(json_path, 'wb') as f:
            f.write(b'{"photoTakenTime":{"timestamp":"1529064000"}}')

        # 2. 建立專案管理目錄 (應被完全忽略)
        for excluded_name in ['_Review', '_ReviewCache', '_Quarantine', '_ImportTemp', '_Excluded']:
            ex_dir = os.path.join(self.folder_dir, excluded_name)
            os.makedirs(ex_dir, exist_ok=True)
            with open(os.path.join(ex_dir, "ignored.jpg"), 'wb') as f:
                f.write(b"ignored photo")

        items = FolderSourceIndexer.index_folder(self.folder_dir)

        # 驗證只有正常目錄下的 2 個條目被索引
        self.assertEqual(len(items), 2)
        filenames = [item.filename for item in items]
        self.assertIn("台北101照片.jpg", filenames)
        self.assertIn("台北101照片.jpg.json", filenames)

        photo_item = next(i for i in items if i.filename == "台北101照片.jpg")
        self.assertTrue(photo_item.is_media)
        self.assertFalse(photo_item.is_json)
        self.assertEqual(photo_item.source_type, "FOLDER")
        self.assertEqual(photo_item.logical_path, "2018年家庭旅遊/台北101照片.jpg")

    def test_folder_source_indexer_reparse_point_and_symlink_skipping(self):
        """驗證一般資料夾唯讀索引：Reparse Point, Junction 與 Symlink 自動跳過不跟隨"""
        real_file = os.path.join(self.folder_dir, "real_photo.jpg")
        with open(real_file, 'wb') as f:
            f.write(b"real photo")

        # 直接驗證 is_reparse_point_or_link 的運作
        self.assertFalse(is_reparse_point_or_link(real_file))

        link_file = os.path.join(self.folder_dir, "link_photo.jpg")
        has_symlink = False
        try:
            os.symlink(real_file, link_file)
            has_symlink = True
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("目前 Windows 權限無法建立 Symlink／Reparse Point，明確略過正向攔截測試")

        if has_symlink:
            self.assertTrue(is_reparse_point_or_link(link_file))

        items = FolderSourceIndexer.index_folder(self.folder_dir)
        filenames = [item.filename for item in items]
        self.assertIn("real_photo.jpg", filenames)
        if has_symlink:
            self.assertNotIn("link_photo.jpg", filenames)

    def test_takeout_source_indexer_read_only_central_directory(self):
        """驗證 Takeout ZIP 唯讀索引：只讀取 ZipInfo 中央目錄，不解壓媒體檔」"""
        zip_path = os.path.join(self.test_dir, "Takeout_Sample.zip")
        photo_bytes = b"Takeout photo sample bytes"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("Takeout/Google Photos/Album/summer.png", photo_bytes)
            zf.writestr("Takeout/Google Photos/Album/summer.png.json", b'{"timestamp":"123456"}')

        items = TakeoutSourceIndexer.index_archives([zip_path])
        self.assertEqual(len(items), 2)

        png_item = next(i for i in items if i.filename == "summer.png")
        self.assertTrue(png_item.is_media)
        self.assertEqual(png_item.source_type, "TAKEOUT_ZIP")
        self.assertEqual(png_item.size, len(photo_bytes))
        self.assertIsNotNone(png_item.archive_fingerprint)
        self.assertIsNotNone(png_item.member_crc)
        self.assertIsNone(png_item.abs_path)

    def test_takeout_source_indexer_invalid_zip_error_raising(self):
        """驗證 Takeout ZIP 唯讀索引：傳入不存在或損毀 ZIP 時明確拋出 ZipSecurityError"""
        invalid_path = os.path.join(self.test_dir, "NonExistent.zip")
        with self.assertRaises(ZipSecurityError):
            TakeoutSourceIndexer.index_archives([invalid_path])


if __name__ == '__main__':
    unittest.main()
