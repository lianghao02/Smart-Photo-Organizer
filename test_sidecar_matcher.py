# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 1 - SidecarMatcher 單元測試 (test_sidecar_matcher.py)
驗證精準配對、裸 stem、Supplemental Metadata (含截斷)、Takeout 編號變體、大小寫相容、跨 ZIP 配對、JSON 獨佔指派、AMBIGUOUS 歧義性與跨目錄備用配對。
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from source_index import SourceItem
from sidecar_matcher import SidecarMatcher, SidecarMatch, MatchOutcome


class TestSidecarMatcher(unittest.TestCase):
    def test_exact_full_path_matching(self):
        """驗證 P1: photo.jpg ↔ photo.jpg.json 同封存檔/同目錄精準全檔名配對"""
        media = SourceItem("m1", "FOLDER", "Album/photo.jpg", "photo.jpg", ".jpg", 100, is_media=True, is_json=False)
        json_item = SourceItem("j1", "FOLDER", "Album/photo.jpg.json", "photo.jpg.json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([media, json_item])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].match_quality, "EXACT_FULL_PATH")
        self.assertEqual(outcome.matched_pairs[0].media_item.filename, "photo.jpg")

    def test_bare_stem_matching(self):
        """驗證 P3: photo.jpg ↔ photo.json 裸 stem 配對"""
        media = SourceItem("m1", "FOLDER", "Album/photo.jpg", "photo.jpg", ".jpg", 100, is_media=True, is_json=False)
        json_item = SourceItem("j1", "FOLDER", "Album/photo.json", "photo.json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([media, json_item])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].match_quality, "BASE_STEM")

    def test_supplemental_metadata_truncated_matching(self):
        """驗證 P2: Supplemental Metadata 及其截斷變體 (例如 photo.jpg.supplemental-metada.json) 配對"""
        media = SourceItem("m1", "FOLDER", "Album/vacation.png", "vacation.png", ".png", 100, is_media=True, is_json=False)
        json_item = SourceItem("j1", "FOLDER", "Album/vacation.png.supplemental-metada.json", "vacation.png.supplemental-metada.json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([media, json_item])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].match_quality, "EXACT_FULL_PATH_SUPPLEMENTAL")

    def test_numbered_variant_matching(self):
        """驗證 P4: photo(1).jpg ↔ photo.jpg(1).json Google Takeout 重複編號變體配對"""
        media_orig = SourceItem("m1", "FOLDER", "Album/photo.jpg", "photo.jpg", ".jpg", 100, is_media=True, is_json=False)
        media_num = SourceItem("m2", "FOLDER", "Album/photo(1).jpg", "photo(1).jpg", ".jpg", 100, is_media=True, is_json=False)

        json_orig = SourceItem("j1", "FOLDER", "Album/photo.jpg.json", "photo.jpg.json", ".json", 50, is_media=False, is_json=True)
        json_num = SourceItem("j2", "FOLDER", "Album/photo.jpg(1).json", "photo.jpg(1).json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([media_orig, media_num, json_orig, json_num])
        self.assertEqual(len(outcome.matched_pairs), 2)

        match1 = next(m for m in outcome.matched_pairs if m.media_item.filename == "photo.jpg")
        self.assertEqual(match1.json_item.filename, "photo.jpg.json")
        self.assertEqual(match1.match_quality, "EXACT_FULL_PATH")

        match2 = next(m for m in outcome.matched_pairs if m.media_item.filename == "photo(1).jpg")
        self.assertEqual(match2.json_item.filename, "photo.jpg(1).json")
        self.assertEqual(match2.match_quality, "NUMBERED_VARIANT")

    def test_case_insensitive_matching_preserves_original_names(self):
        """驗證大小寫不符時仍可精準配對，且輸出物件保留原始檔名名稱"""
        media = SourceItem("m1", "FOLDER", "Album/PHOTO_2018.JPG", "PHOTO_2018.JPG", ".jpg", 100, is_media=True, is_json=False)
        json_item = SourceItem("j1", "FOLDER", "Album/photo_2018.jpg.json", "photo_2018.jpg.json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([media, json_item])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].media_item.filename, "PHOTO_2018.JPG")
        self.assertEqual(outcome.matched_pairs[0].json_item.filename, "photo_2018.jpg.json")

    def test_cross_zip_exact_logical_path_matching(self):
        """驗證 P5: 跨 ZIP 媒體與 Sidecar 相同邏輯路徑配對 (CROSS_ZIP_EXACT) 且與同 ZIP P1 明確區分"""
        media_zip1 = SourceItem("zip1:m1", "TAKEOUT_ZIP", "Photos/sun.heic", "sun.heic", ".heic", 100, is_media=True, is_json=False, archive_fingerprint="fp1")
        json_zip2 = SourceItem("zip2:j1", "TAKEOUT_ZIP", "Photos/sun.heic.json", "sun.heic.json", ".json", 50, is_media=False, is_json=True, archive_fingerprint="fp2")

        outcome = SidecarMatcher.match_sources([media_zip1, json_zip2])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].match_quality, "CROSS_ZIP_EXACT")

    def test_exclusive_single_json_assignment(self):
        """驗證單一 JSON 絕不會重覆指派給多個媒體"""
        media1 = SourceItem("m1", "FOLDER", "DirA/pic.jpg", "pic.jpg", ".jpg", 100, is_media=True, is_json=False)
        media2 = SourceItem("m2", "FOLDER", "DirB/pic.jpg", "pic.jpg", ".jpg", 100, is_media=True, is_json=False)
        json_item = SourceItem("j1", "FOLDER", "DirA/pic.jpg.json", "pic.jpg.json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([media1, media2, json_item])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].media_item.logical_path, "DirA/pic.jpg")
        self.assertEqual(len(outcome.unmatched_media), 1)

    def test_ambiguous_candidates_marked_without_arbitrary_choice(self):
        """驗證同優先序多候選時標記 AMBIGUOUS，且結果不隨輸入順序改變"""
        media = SourceItem("m1", "FOLDER", "Album/dup.jpg", "dup.jpg", ".jpg", 100, is_media=True, is_json=False)
        json1 = SourceItem("j1", "FOLDER", "DirX/dup.jpg.json", "dup.jpg.json", ".json", 50, is_media=False, is_json=True)
        json2 = SourceItem("j2", "FOLDER", "DirY/dup.jpg.json", "dup.jpg.json", ".json", 50, is_media=False, is_json=True)

        # 順序 1
        outcome1 = SidecarMatcher.match_sources([media, json1, json2])
        self.assertEqual(len(outcome1.matched_pairs), 0)
        self.assertEqual(len(outcome1.ambiguous_media), 1)

        # 順序 2
        outcome2 = SidecarMatcher.match_sources([media, json2, json1])
        self.assertEqual(len(outcome2.matched_pairs), 0)
        self.assertEqual(len(outcome2.ambiguous_media), 1)

    def test_cross_folder_filename_fallback_unique_candidate(self):
        """驗證 P6: 跨資料夾檔名備用配對僅在全任務候選唯一時成功"""
        media = SourceItem("m1", "FOLDER", "FolderA/camera.jpg", "camera.jpg", ".jpg", 100, is_media=True, is_json=False)
        json_item = SourceItem("j1", "FOLDER", "FolderB/camera.jpg.json", "camera.jpg.json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([media, json_item])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].match_quality, "FILENAME_MATCH")

    def test_global_priority_phase_order_prevents_p6_stealing_p1(self):
        """驗證全域階段式優先序：高優先序 (P1) 跨全任務優先於低優先序 (P6) 搶奪」"""
        mediaA = SourceItem("mA", "FOLDER", "FolderA/img.jpg", "img.jpg", ".jpg", 100, is_media=True, is_json=False)
        mediaB = SourceItem("mB", "FOLDER", "FolderB/img.jpg", "img.jpg", ".jpg", 100, is_media=True, is_json=False)

        jsonB = SourceItem("jB", "FOLDER", "FolderB/img.jpg.json", "img.jpg.json", ".json", 50, is_media=False, is_json=True)

        outcome = SidecarMatcher.match_sources([mediaA, mediaB, jsonB])
        self.assertEqual(len(outcome.matched_pairs), 1)
        self.assertEqual(outcome.matched_pairs[0].media_item.logical_path, "FolderB/img.jpg")
        self.assertEqual(outcome.matched_pairs[0].match_quality, "EXACT_FULL_PATH")

    def test_folder_and_zip_identical_matching_quality(self):
        """驗證一般資料夾與 Takeout ZIP 對等案例產生完全相同的配對品質"""
        folder_m = SourceItem("f_m", "FOLDER", "Album/img.jpg", "img.jpg", ".jpg", 100, is_media=True, is_json=False)
        folder_j = SourceItem("f_j", "FOLDER", "Album/img.jpg.json", "img.jpg.json", ".json", 50, is_media=False, is_json=True)
        res_f = SidecarMatcher.match_sources([folder_m, folder_j])

        zip_m = SourceItem("z_m", "TAKEOUT_ZIP", "Album/img.jpg", "img.jpg", ".jpg", 100, is_media=True, is_json=False, archive_fingerprint="fp1")
        zip_j = SourceItem("z_j", "TAKEOUT_ZIP", "Album/img.jpg.json", "img.jpg.json", ".json", 50, is_media=False, is_json=True, archive_fingerprint="fp1")
        res_z = SidecarMatcher.match_sources([zip_m, zip_j])

        self.assertEqual(res_f.matched_pairs[0].match_quality, res_z.matched_pairs[0].match_quality)
        self.assertEqual(res_f.matched_pairs[0].match_quality, "EXACT_FULL_PATH")


if __name__ == '__main__':
    unittest.main()
