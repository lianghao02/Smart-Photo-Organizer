# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 跨 ZIP 媒體與 Sidecar JSON 索引配對模組
可以在不安裝/不解壓實體檔案的情況下，預先配對跨包 JSON 與產出「ZIP 快速盤點報告」。
"""

import os
from typing import List, Dict, Any, Tuple
from import_state import TakeoutStateManager


class TakeoutIndexer:
    def __init__(self, state_mgr: TakeoutStateManager):
        self.state_mgr = state_mgr

    def build_cross_zip_index(self, job_id: str) -> Dict[str, Any]:
        """
        掃描 SQLite 中指定 job_id 的所有成員，建立 Sidecar JSON 配對
        回傳「ZIP 快速盤點報告」數據結構
        """
        # 1. 取得所有媒體與 JSON 成員
        media_members = self.state_mgr.get_job_members_by_status(job_id, "SECURITY_VALIDATED")
        
        # 建立 JSON 查找表： key 為 normalized_path 或 filename
        json_by_full_path = {}
        json_by_stem_path = {}
        json_by_filename = {}

        # 重新整理清單
        media_list = []
        json_count = 0
        media_count = 0
        total_uncompressed_size = 0
        rejected_count = 0

        # 全量讀取此 job 的成員
        with self.state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM members WHERE job_id = ?", (job_id,))
            rows = [dict(r) for r in cursor.fetchall()]

        for m in rows:
            total_uncompressed_size += m['uncompressed_size']
            if m['status'] == 'SECURITY_REJECTED':
                rejected_count += 1
                continue

            if m['is_json']:
                json_count += 1
                norm_p = m['normalized_path'].lower()
                json_by_full_path[norm_p] = m

                # stem 匹配 (去掉 .json 的前綴)
                if norm_p.endswith('.json'):
                    stem = norm_p[:-5]
                    json_by_stem_path[stem] = m

                fn = m['filename'].lower()
                if fn not in json_by_filename:
                    json_by_filename[fn] = []
                json_by_filename[fn].append(m)

            elif m['is_media']:
                media_count += 1
                media_list.append(m)

        # 2. 為每個媒體進行 4 階段 Sidecar 配對
        matched_pair_count = 0
        unmatched_media_count = 0

        for media in media_list:
            norm_p = media['normalized_path'].lower()
            matched_json = None
            match_quality = "NONE"

            # 優先配對 1: 同路徑全檔名 + .json (e.g. IMG_001.JPG.json)
            full_json_key = norm_p + ".json"
            if full_json_key in json_by_full_path:
                matched_json = json_by_full_path[full_json_key]
                match_quality = "EXACT_FULL_PATH"

            # 優先配對 2: 同路徑 stem + .json (e.g. IMG_001.json)
            elif norm_p in json_by_stem_path:
                matched_json = json_by_stem_path[norm_p]
                match_quality = "EXACT_STEM"

            # 優先配對 3: 同檔名 + .json (跨資料夾/跨 ZIP)
            else:
                fn_key = (media['filename'] + ".json").lower()
                if fn_key in json_by_filename and len(json_by_filename[fn_key]) == 1:
                    matched_json = json_by_filename[fn_key][0]
                    match_quality = "FILENAME_MATCH"

            if matched_json:
                matched_pair_count += 1
                # 寫入 SQLite sidecar_links
                with self.state_mgr._get_conn() as conn:
                    conn.execute(
                        "INSERT INTO sidecar_links (job_id, media_member_id, json_member_id, match_quality) VALUES (?, ?, ?, ?)",
                        (job_id, media['member_id'], matched_json['member_id'], match_quality)
                    )
            else:
                unmatched_media_count += 1

            # 狀態更新為 INDEXED
            self.state_mgr.update_member_status(media['member_id'], "INDEXED")

        # 3. 組合「ZIP 快速盤點報告」
        audit_report = {
            "job_id": job_id,
            "media_count": media_count,
            "json_count": json_count,
            "matched_pair_count": matched_pair_count,
            "unmatched_media_count": unmatched_media_count,
            "unmatched_json_count": max(0, json_count - matched_pair_count),
            "total_uncompressed_bytes": total_uncompressed_size,
            "total_uncompressed_gb": round(total_uncompressed_size / (1024 ** 3), 2),
            "security_rejected_count": rejected_count
        }

        return audit_report
