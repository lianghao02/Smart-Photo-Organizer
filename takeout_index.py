# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - 跨 ZIP 媒體與 Sidecar JSON 索引配對模組 (v3.2 呼叫 SidecarMatcher 版)
包裝 SidecarMatcher 配對引擎，保留既有 TakeoutIndexer API、SQLite sidecar_links 寫入、單向狀態保護與盤點報告契約。
"""

import os
import re
from typing import List, Dict, Any, Set, Tuple, Optional
from import_state import TakeoutStateManager, TakeoutState
from source_index import SourceItem
from sidecar_matcher import SidecarMatcher


class TakeoutIndexer:
    def __init__(self, state_mgr: TakeoutStateManager):
        self.state_mgr = state_mgr

    @staticmethod
    def _extract_json_stem(norm_p: str) -> Tuple[str, str]:
        """相容靜態方法：從 JSON 的 normalized_path 中解析出相對應的媒體 stem 與全名"""
        return SidecarMatcher._extract_json_stem(norm_p)

    def build_cross_zip_index(self, job_id: str) -> Dict[str, Any]:
        """
        掃描 SQLite 中指定 job_id 的所有成員，經由 SidecarMatcher 建立 Sidecar JSON 配對
        回傳「ZIP 快速盤點報告」數據結構
        """
        with self.state_mgr._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM members WHERE job_id = ?", (job_id,))
            rows = [dict(r) for r in cursor.fetchall()]

        total_uncompressed_size = 0
        rejected_count = 0
        media_count = 0
        json_count = 0

        source_items: List[SourceItem] = []
        db_id_map: Dict[str, int] = {}

        for m in rows:
            total_uncompressed_size += m['uncompressed_size']
            if m['status'] == 'SECURITY_REJECTED':
                rejected_count += 1
                continue

            if m['is_json']:
                json_count += 1
            elif m['is_media']:
                media_count += 1

            key = f"db:{m['member_id']}"
            item = SourceItem(
                source_key=key,
                source_type="TAKEOUT_ZIP",
                logical_path=m['normalized_path'],
                filename=m['filename'],
                extension=os.path.splitext(m['filename'])[1].lower(),
                size=m['uncompressed_size'],
                is_media=bool(m['is_media']),
                is_json=bool(m['is_json']),
                is_safe=True,
                archive_fingerprint=m.get('archive_fingerprint'),
                member_index=m.get('member_index'),
                member_crc=m.get('member_crc')
            )
            source_items.append(item)
            db_id_map[key] = m['member_id']

        # 呼叫純 SidecarMatcher 進行精準優先序配對
        outcome = SidecarMatcher.match_sources(source_items)

        sidecar_rows = []
        assigned_json_ids: Set[int] = set()

        for match in outcome.matched_pairs:
            m_id = db_id_map[match.media_item.source_key]
            j_id = db_id_map[match.json_item.source_key]
            assigned_json_ids.add(j_id)
            sidecar_rows.append((job_id, m_id, j_id, match.match_quality))

        # 僅針對處於 SECURITY_VALIDATED 或 DISCOVERED 狀態的媒體更新為 INDEXED (保護已 VERIFIED / COMPLETED 狀態)
        indexed_media_ids = [
            m['member_id'] for m in rows
            if m['is_media'] and m['status'] in (TakeoutState.SECURITY_VALIDATED, TakeoutState.DISCOVERED)
        ]

        # 批次寫入 sidecar_links
        if sidecar_rows:
            with self.state_mgr._get_conn() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO sidecar_links (job_id, media_member_id, json_member_id, match_quality) VALUES (?, ?, ?, ?)",
                    sidecar_rows
                )

        # 高效能批次更新媒體狀態為 INDEXED (單向狀態保護)
        if indexed_media_ids:
            self.state_mgr.update_members_status_batch(indexed_media_ids, TakeoutState.INDEXED)

        audit_report = {
            "job_id": job_id,
            "media_count": media_count,
            "json_count": json_count,
            "matched_pair_count": len(outcome.matched_pairs),
            "unmatched_media_count": len(outcome.unmatched_media) + len(outcome.ambiguous_media),
            "unmatched_json_count": max(0, json_count - len(assigned_json_ids)),
            "total_uncompressed_bytes": total_uncompressed_size,
            "total_uncompressed_gb": round(total_uncompressed_size / (1024 ** 3), 2),
            "security_rejected_count": rejected_count
        }

        return audit_report
