# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 跨 ZIP 媒體與 Sidecar JSON 索引配對模組 (v1.1 修補版)
修復 stem 匹配、.supplemental-metadata.json 解析與不重複配對計數。
"""

import os
from typing import List, Dict, Any, Set
from import_state import TakeoutStateManager


class TakeoutIndexer:
    def __init__(self, state_mgr: TakeoutStateManager):
        self.state_mgr = state_mgr

    @staticmethod
    def _extract_json_stem(norm_p: str) -> Tuple[str, str]:
        """
        從 JSON 的 normalized_path 中解析出相對應的媒體 stem 與全名
        支援 .json 以及 .supplemental-metadata.json
        """
        lower_p = norm_p.lower()
        if lower_p.endswith('.supplemental-metadata.json'):
            stem = norm_p[:-27]  # 去除 .supplemental-metadata.json
        elif lower_p.endswith('.json'):
            stem = norm_p[:-5]   # 去除 .json
        else:
            stem = norm_p
        return stem, os.path.basename(stem)

    def build_cross_zip_index(self, job_id: str) -> Dict[str, Any]:
        """
        掃描 SQLite 中指定 job_id 的所有成員，建立 Sidecar JSON 配對
        回傳「ZIP 快速盤點報告」數據結構
        """
        # 全量讀取此 job 的成員
        with self.state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM members WHERE job_id = ?", (job_id,))
            rows = [dict(r) for r in cursor.fetchall()]

        json_by_full_path = {}
        json_by_stem_path = {}
        json_by_filename = {}

        media_list = []
        json_count = 0
        media_count = 0
        total_uncompressed_size = 0
        rejected_count = 0

        for m in rows:
            total_uncompressed_size += m['uncompressed_size']
            if m['status'] == 'SECURITY_REJECTED':
                rejected_count += 1
                continue

            if m['is_json']:
                json_count += 1
                norm_p = m['normalized_path'].lower()
                json_by_full_path[norm_p] = m

                stem, fn_stem = self._extract_json_stem(norm_p)
                stem_lower = stem.lower()
                json_by_stem_path[stem_lower] = m

                # 去除副檔名後的 stem (例如包含照片副檔名的與沒包含的)
                media_base_stem = os.path.splitext(stem_lower)[0]
                json_by_stem_path[media_base_stem] = m

                fn_lower = m['filename'].lower()
                if fn_lower not in json_by_filename:
                    json_by_filename[fn_lower] = []
                json_by_filename[fn_lower].append(m)

            elif m['is_media']:
                media_count += 1
                media_list.append(m)

        # 配對紀錄與單一 JSON 賦予集合 (防止同一 JSON 重複計算)
        matched_pair_count = 0
        unmatched_media_count = 0
        assigned_json_ids: Set[int] = set()
        sidecar_rows = []

        for media in media_list:
            norm_p = media['normalized_path'].lower()
            media_stem = os.path.splitext(norm_p)[0]
            matched_json = None
            match_quality = "NONE"

            # 配對 1: 同路徑全檔名 + .json 或 .supplemental-metadata.json
            cand_full_1 = norm_p + ".json"
            cand_full_2 = norm_p + ".supplemental-metadata.json"
            if cand_full_1 in json_by_full_path:
                matched_json = json_by_full_path[cand_full_1]
                match_quality = "EXACT_FULL_PATH"
            elif cand_full_2 in json_by_full_path:
                matched_json = json_by_full_path[cand_full_2]
                match_quality = "EXACT_FULL_PATH_SUPPLEMENTAL"

            # 配對 2: 同路徑 stem + .json (e.g. IMG_001.png 匹配 IMG_001.json 或 IMG_001.png.json)
            elif norm_p in json_by_stem_path:
                matched_json = json_by_stem_path[norm_p]
                match_quality = "EXACT_STEM"
            elif media_stem in json_by_stem_path:
                matched_json = json_by_stem_path[media_stem]
                match_quality = "BASE_STEM"

            # 配對 3: 同檔名 JSON (跨資料夾/跨 ZIP)
            else:
                fn_cand_1 = (media['filename'] + ".json").lower()
                fn_cand_2 = (media['filename'] + ".supplemental-metadata.json").lower()
                if fn_cand_1 in json_by_filename and len(json_by_filename[fn_cand_1]) == 1:
                    matched_json = json_by_filename[fn_cand_1][0]
                    match_quality = "FILENAME_MATCH"
                elif fn_cand_2 in json_by_filename and len(json_by_filename[fn_cand_2]) == 1:
                    matched_json = json_by_filename[fn_cand_2][0]
                    match_quality = "FILENAME_SUPPLEMENTAL_MATCH"

            if matched_json:
                matched_pair_count += 1
                assigned_json_ids.add(matched_json['member_id'])
                sidecar_rows.append((job_id, media['member_id'], matched_json['member_id'], match_quality))
            else:
                unmatched_media_count += 1

            # 狀態更新為 INDEXED
            self.state_mgr.update_member_status(media['member_id'], "INDEXED")

        # 批次寫入 sidecar_links
        if sidecar_rows:
            with self.state_mgr._get_conn() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO sidecar_links (job_id, media_member_id, json_member_id, match_quality) VALUES (?, ?, ?, ?)",
                    sidecar_rows
                )

        audit_report = {
            "job_id": job_id,
            "media_count": media_count,
            "json_count": json_count,
            "matched_pair_count": matched_pair_count,
            "unmatched_media_count": unmatched_media_count,
            "unmatched_json_count": max(0, json_count - len(assigned_json_ids)),
            "total_uncompressed_bytes": total_uncompressed_size,
            "total_uncompressed_gb": round(total_uncompressed_size / (1024 ** 3), 2),
            "security_rejected_count": rejected_count
        }

        return audit_report
