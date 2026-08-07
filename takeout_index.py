# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 跨 ZIP 媒體與 Sidecar JSON 索引配對模組 (v1.3 修補版)
修復 Tuple 匯入缺失、截斷 supplemental metadata、全型/裸 stem 檢索、JSON 獨佔指派與批次更新。
"""

import os
import re
from typing import List, Dict, Any, Set, Tuple, Optional
from import_state import TakeoutStateManager


class TakeoutIndexer:
    def __init__(self, state_mgr: TakeoutStateManager):
        self.state_mgr = state_mgr

    @staticmethod
    def _extract_json_stem(norm_p: str) -> Tuple[str, str]:
        """
        從 JSON 的 normalized_path 中解析出相對應的媒體 stem 與全名
        支援 .json 以及截斷的 .supplemental-metadata.json 變體 (例如 .supplemental-metada.json)
        """
        lower_p = norm_p.lower()
        m = re.search(r'\.supplemental[^/]*\.json$', lower_p)
        if m:
            stem = norm_p[:m.start()]
        elif lower_p.endswith('.json'):
            stem = norm_p[:-5]
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

        json_by_full_path: Dict[str, dict] = {}
        json_by_stem_path: Dict[str, dict] = {}
        json_by_filename: Dict[str, List[dict]] = {}

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

                # 1. 完整相對路徑 stem (例如 takeout/album/img_002.heic)
                json_by_stem_path[stem_lower] = m

                # 2. 裸 stem (例如 takeout/album/img_002)
                media_base_stem = os.path.splitext(stem_lower)[0]
                json_by_stem_path[media_base_stem] = m

                fn_lower = m['filename'].lower()
                if fn_lower not in json_by_filename:
                    json_by_filename[fn_lower] = []
                json_by_filename[fn_lower].append(m)

            elif m['is_media']:
                media_count += 1
                media_list.append(m)

        # 配對紀錄與單一 JSON 獨佔賦予集合
        matched_pair_count = 0
        unmatched_media_count = 0
        assigned_json_ids: Set[int] = set()
        sidecar_rows = []
        indexed_media_ids = []

        for media in media_list:
            norm_p = media['normalized_path'].lower()
            media_stem = os.path.splitext(norm_p)[0]
            matched_json = None
            match_quality = "NONE"

            # 1. 優先匹配：直接在 json_by_stem_path 中尋找 norm_p (例如包含了 .heic 等完整副檔名的裸 stem)
            if norm_p in json_by_stem_path:
                cand = json_by_stem_path[norm_p]
                if cand['member_id'] not in assigned_json_ids:
                    matched_json = cand
                    match_quality = "EXACT_MEDIA_FULL_PATH"

            # 2. 其次嘗試拼接 .json 與 .supplemental 檔名
            if not matched_json:
                candidates = [
                    (norm_p + ".json", "EXACT_FULL_PATH"),
                    (norm_p + ".supplemental-metadata.json", "EXACT_FULL_PATH_SUPPLEMENTAL"),
                    (media_stem + ".json", "BASE_STEM"),
                    (media_stem + ".supplemental-metadata.json", "BASE_STEM_SUPPLEMENTAL"),
                ]

                for key, qual in candidates:
                    if key in json_by_full_path:
                        cand = json_by_full_path[key]
                        if cand['member_id'] not in assigned_json_ids:
                            matched_json = cand
                            match_quality = qual
                            break
                    elif key in json_by_stem_path:
                        cand = json_by_stem_path[key]
                        if cand['member_id'] not in assigned_json_ids:
                            matched_json = cand
                            match_quality = qual
                            break

            # 3. 最後嘗試檔名匹配 (跨資料夾/跨 ZIP)
            if not matched_json:
                fn_cands = [
                    (media['filename'] + ".json").lower(),
                    (media['filename'] + ".supplemental-metadata.json").lower(),
                    (os.path.basename(media_stem) + ".json").lower(),
                ]
                for fn_key in fn_cands:
                    if fn_key in json_by_filename:
                        unassigned = [j for j in json_by_filename[fn_key] if j['member_id'] not in assigned_json_ids]
                        if len(unassigned) == 1:
                            matched_json = unassigned[0]
                            match_quality = "FILENAME_MATCH"
                            break

            if matched_json:
                matched_pair_count += 1
                assigned_json_ids.add(matched_json['member_id'])
                sidecar_rows.append((job_id, media['member_id'], matched_json['member_id'], match_quality))
            else:
                unmatched_media_count += 1

            indexed_media_ids.append(media['member_id'])

        # 批次寫入 sidecar_links
        if sidecar_rows:
            with self.state_mgr._get_conn() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO sidecar_links (job_id, media_member_id, json_member_id, match_quality) VALUES (?, ?, ?, ?)",
                    sidecar_rows
                )

        # 高效能批次更新媒體狀態為 INDEXED
        self.state_mgr.update_members_status_batch(indexed_media_ids, "INDEXED")

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
