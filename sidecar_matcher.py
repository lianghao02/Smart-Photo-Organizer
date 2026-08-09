# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 1 - 獨立 Sidecar 決策配對模組 (sidecar_matcher.py)
提供完全獨立於 SQLite、檔案搬移與 UI 的純函數式 SidecarMatcher，
支援全檔名、Supplemental Metadata (含截斷變體)、裸 stem、Google Takeout 重複編號、跨 ZIP 邏輯路徑與跨目錄單一備用配對。
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional
from source_index import SourceItem
from media_types import EXT_PHOTOS, EXT_VIDEOS, EXT_MEDIA


@dataclass
class SidecarMatch:
    """單一 Sidecar 配對結果"""
    media_item: SourceItem
    json_item: SourceItem
    match_quality: str      # 例如: EXACT_FULL_PATH, EXACT_FULL_PATH_SUPPLEMENTAL, BASE_STEM, NUMBERED_VARIANT, CROSS_ZIP_EXACT, FILENAME_MATCH
    reason: str             # 人類可讀的的配對說明文字


@dataclass
class MatchOutcome:
    """Sidecar 配對總體輸出結果"""
    matched_pairs: List[SidecarMatch] = field(default_factory=list)
    unmatched_media: List[SourceItem] = field(default_factory=list)
    unmatched_json: List[SourceItem] = field(default_factory=list)
    ambiguous_media: List[SourceItem] = field(default_factory=list)
    ambiguous_json: List[SourceItem] = field(default_factory=list)


class SidecarMatcher:
    """純 Sidecar 配對引擎"""

    @staticmethod
    def _extract_json_stem(norm_p: str) -> Tuple[str, str]:
        """從 JSON 的 normalized/logical_path 中解析出相對應的媒體 stem 與檔名"""
        lower_p = norm_p.lower()
        m = re.search(r'\.supplemental[^/]*\.json$', lower_p)
        if m:
            stem = norm_p[:m.start()]
        elif lower_p.endswith('.json'):
            stem = norm_p[:-5]
        else:
            stem = norm_p
        return stem, os.path.basename(stem)

    @classmethod
    def match_sources(cls, items: List[SourceItem]) -> MatchOutcome:
        """
        對輸入的 SourceItem 列表進行精準優先序 Sidecar 配對。
        規則：
        1. 一個 JSON 最多賦予給一個媒體。
        2. 比較時不區分大小寫，但輸出保留原始物件名稱。
        3. 優先序階層：
           - P1: 同邏輯目錄、全媒體檔名 + .json (例如 photo.jpg ↔ photo.jpg.json)
           - P2: 同邏輯目錄、Supplemental Metadata 及其截斷變體 (例如 photo.jpg.supplemental-metadata.json)
           - P3: 同邏輯目錄、裸 stem + .json (例如 photo.jpg ↔ photo.json)
           - P4: Google Takeout 重複編號變體 (例如 photo(1).jpg ↔ photo.jpg(1).json)
           - P5: 跨 ZIP / 跨封存檔、相同邏輯路徑配對
           - P6: 跨資料夾檔名備用配對 (僅在全任務候選唯一時生效)
        4. 同優先序若有多個候選，標記 AMBIGUOUS，結果決定性排序。
        """
        outcome = MatchOutcome()
        if not items:
            return outcome

        # 分離媒體與 JSON 項目 (排除不安全項目)
        media_items: List[SourceItem] = []
        json_items: List[SourceItem] = []

        for item in items:
            if not item.is_safe:
                continue
            if item.is_json:
                json_items.append(item)
            elif item.is_media:
                media_items.append(item)

        # 建立索引對照表
        # 1. 完整邏輯路徑 ➔ JSON items 列表
        json_by_logical_path: Dict[str, List[SourceItem]] = {}
        # 2. 裸 stem 邏輯路徑 ➔ JSON items 列表
        json_by_stem_path: Dict[str, List[SourceItem]] = {}
        # 3. 檔名 (小寫) ➔ JSON items 列表
        json_by_filename: Dict[str, List[SourceItem]] = {}

        for j in json_items:
            log_p_lower = j.logical_path.lower()
            if log_p_lower not in json_by_logical_path:
                json_by_logical_path[log_p_lower] = []
            json_by_logical_path[log_p_lower].append(j)

            stem, _ = cls._extract_json_stem(log_p_lower)
            if stem not in json_by_stem_path:
                json_by_stem_path[stem] = []
            json_by_stem_path[stem].append(j)

            # 裸 stem 檔名基礎
            base_stem = os.path.splitext(stem)[0]
            if base_stem not in json_by_stem_path:
                json_by_stem_path[base_stem] = []
            json_by_stem_path[base_stem].append(j)

            fn_lower = j.filename.lower()
            if fn_lower not in json_by_filename:
                json_by_filename[fn_lower] = []
            json_by_filename[fn_lower].append(j)

        assigned_json_keys: Set[str] = set()
        ambiguous_json_keys: Set[str] = set()

        # 決定性排序媒體條目
        media_items.sort(key=lambda x: x.source_key)

        for media in media_items:
            log_p = media.logical_path.lower()
            log_dir = os.path.dirname(log_p)
            media_stem = os.path.splitext(log_p)[0]
            fn_lower = media.filename.lower()
            fn_stem = os.path.splitext(fn_lower)[0]

            matched_json: Optional[SourceItem] = None
            match_quality: Optional[str] = None
            match_reason: str = ""

            # Helper 函式取得未分配且未被標記為歧義的候選
            def get_unassigned(cands: List[SourceItem]) -> List[SourceItem]:
                return [c for c in cands if c.source_key not in assigned_json_keys and c.source_key not in ambiguous_json_keys]

            # Priority 1: 同邏輯目錄、全媒體檔名 + .json (例如 photo.jpg.json)
            p1_key = log_p + ".json"
            if p1_key in json_by_logical_path:
                valid_cands = get_unassigned(json_by_logical_path[p1_key])
                if len(valid_cands) == 1:
                    matched_json = valid_cands[0]
                    match_quality = "EXACT_FULL_PATH"
                    match_reason = "同目錄全檔名精準配對 (.jpg.json)"
                elif len(valid_cands) > 1:
                    outcome.ambiguous_media.append(media)
                    for c in valid_cands:
                        ambiguous_json_keys.add(c.source_key)
                    continue

            # Priority 2: 同邏輯目錄、Supplemental Metadata 及其截斷變體
            if not matched_json:
                p2_candidates = [
                    log_p + ".supplemental-metadata.json",
                    log_p + ".supplemental-metada.json",
                    log_p + ".supplemental-meta.json",
                    log_p + ".supplemental.json",
                ]
                for p2_key in p2_candidates:
                    if p2_key in json_by_logical_path:
                        valid_cands = get_unassigned(json_by_logical_path[p2_key])
                        if len(valid_cands) == 1:
                            matched_json = valid_cands[0]
                            match_quality = "EXACT_FULL_PATH_SUPPLEMENTAL"
                            match_reason = "同目錄 Supplemental Metadata 配對"
                            break
                        elif len(valid_cands) > 1:
                            outcome.ambiguous_media.append(media)
                            for c in valid_cands:
                                ambiguous_json_keys.add(c.source_key)
                            break
                if media in outcome.ambiguous_media:
                    continue

            # Priority 3: 同邏輯目錄、裸 stem + .json (例如 photo.jpg ↔ photo.json)
            if not matched_json:
                p3_key = media_stem + ".json"
                if p3_key in json_by_logical_path or p3_key in json_by_stem_path:
                    raw_cands = json_by_logical_path.get(p3_key, []) + json_by_stem_path.get(p3_key, [])
                    # 去重
                    unique_cands_dict = {c.source_key: c for c in raw_cands}
                    valid_cands = get_unassigned(list(unique_cands_dict.values()))
                    
                    # Live Photo 保護：若是影片且同目錄有相片存在，不搶奪裸 stem.json
                    if media.extension in EXT_VIDEOS:
                        has_sibling_photo = any(
                            m != media and os.path.dirname(m.logical_path.lower()) == log_dir
                            and os.path.splitext(m.logical_path.lower())[0] == media_stem
                            and m.extension in EXT_PHOTOS
                            for m in media_items
                        )
                        if has_sibling_photo:
                            valid_cands = []

                    if len(valid_cands) == 1:
                        matched_json = valid_cands[0]
                        match_quality = "BASE_STEM"
                        match_reason = "同目錄裸 stem 配對 (.json)"
                    elif len(valid_cands) > 1:
                        outcome.ambiguous_media.append(media)
                        for c in valid_cands:
                            ambiguous_json_keys.add(c.source_key)
                        continue

            # Priority 4: Google Takeout 重複編號變體 (例如 photo(1).jpg ↔ photo.jpg(1).json 或 photo(1).jpg.json)
            if not matched_json:
                m_num = re.search(r'^(.*?)(\(\d+\))$', fn_stem)
                if m_num:
                    raw_base, num_part = m_num.group(1), m_num.group(2)
                    p4_candidates = [
                        os.path.join(log_dir, f"{raw_base}{media.extension}{num_part}.json").replace('\\', '/').strip('/'),
                        os.path.join(log_dir, f"{fn_stem}{media.extension}.json").replace('\\', '/').strip('/'),
                        os.path.join(log_dir, f"{fn_stem}.json").replace('\\', '/').strip('/'),
                    ]
                    for p4_key in p4_candidates:
                        if p4_key in json_by_logical_path:
                            valid_cands = get_unassigned(json_by_logical_path[p4_key])
                            if len(valid_cands) == 1:
                                matched_json = valid_cands[0]
                                match_quality = "NUMBERED_VARIANT"
                                match_reason = "Google Takeout 重複編號變體配對"
                                break
                            elif len(valid_cands) > 1:
                                outcome.ambiguous_media.append(media)
                                for c in valid_cands:
                                    ambiguous_json_keys.add(c.source_key)
                                break
                    if media in outcome.ambiguous_media:
                        continue

            # Priority 5: 跨 ZIP / 跨封存檔相同邏輯路徑配對
            if not matched_json:
                if p1_key in json_by_logical_path:
                    valid_cands = get_unassigned(json_by_logical_path[p1_key])
                    if len(valid_cands) == 1:
                        matched_json = valid_cands[0]
                        match_quality = "CROSS_ZIP_EXACT"
                        match_reason = "跨 ZIP 相同邏輯路徑配對"
                    elif len(valid_cands) > 1:
                        outcome.ambiguous_media.append(media)
                        for c in valid_cands:
                            ambiguous_json_keys.add(c.source_key)
                        continue

            # Priority 6: 跨資料夾檔名備用配對 (僅在全任務候選唯一時生效)
            if not matched_json:
                p6_fn_keys = [
                    (fn_lower + ".json"),
                    (fn_lower + ".supplemental-metadata.json"),
                    (fn_stem + ".json")
                ]
                for p6_key in p6_fn_keys:
                    if p6_key in json_by_filename:
                        valid_cands = get_unassigned(json_by_filename[p6_key])
                        if len(valid_cands) == 1:
                            matched_json = valid_cands[0]
                            match_quality = "FILENAME_MATCH"
                            match_reason = "跨目錄單一檔名備用配對"
                            break
                        elif len(valid_cands) > 1:
                            outcome.ambiguous_media.append(media)
                            for c in valid_cands:
                                ambiguous_json_keys.add(c.source_key)
                            break
                if media in outcome.ambiguous_media:
                    continue

            # 配對成功登記
            if matched_json:
                assigned_json_keys.add(matched_json.source_key)
                outcome.matched_pairs.append(SidecarMatch(
                    media_item=media,
                    json_item=matched_json,
                    match_quality=match_quality or "UNKNOWN",
                    reason=match_reason
                ))
            else:
                outcome.unmatched_media.append(media)

        # 整理未配對與歧義 JSON
        for j in json_items:
            if j.source_key in ambiguous_json_keys:
                outcome.ambiguous_json.append(j)
            elif j.source_key not in assigned_json_keys:
                outcome.unmatched_json.append(j)

        # 決定性排序所有結果
        outcome.matched_pairs.sort(key=lambda x: x.media_item.source_key)
        outcome.unmatched_media.sort(key=lambda x: x.source_key)
        outcome.unmatched_json.sort(key=lambda x: x.source_key)
        outcome.ambiguous_media.sort(key=lambda x: x.source_key)
        outcome.ambiguous_json.sort(key=lambda x: x.source_key)

        return outcome
