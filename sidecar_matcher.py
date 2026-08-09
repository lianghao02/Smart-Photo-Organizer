# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 1 - 獨立 Sidecar 決策配對模組 (sidecar_matcher.py)
提供完全獨立於 SQLite、檔案搬移與 UI 的純函數式 SidecarMatcher，
採用全域階段式 (Phase-by-Phase) 優先序配對算法，明確區分同封存檔 P1 與跨封存檔 P5。
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
    """純 Sidecar 配對引擎 (全域階段式優先序)"""

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

    @staticmethod
    def is_same_archive(m: SourceItem, j: SourceItem) -> bool:
        """檢查媒體與 JSON 是否來自同一個實體 ZIP 封存檔或同一個一般資料夾目錄"""
        if m.source_type == "TAKEOUT_ZIP" and j.source_type == "TAKEOUT_ZIP":
            return bool(m.archive_fingerprint and m.archive_fingerprint == j.archive_fingerprint)
        elif m.source_type == "FOLDER" and j.source_type == "FOLDER":
            return os.path.dirname(m.logical_path.lower()) == os.path.dirname(j.logical_path.lower())
        return False

    @classmethod
    def find_sidecars_for_media(cls, media: SourceItem, candidate_items: List[SourceItem]) -> List[SidecarMatch]:
        """
        為單一媒體在同目錄的候選 JSON 中尋找所有合法的 Sidecar (支援同媒體跟隨全檔名與裸 stem 複數 Sidecar)。
        供 Processor._get_sidecar_pairs() 實際調用，共用同套配對規則與優先序。
        """
        matches: List[SidecarMatch] = []
        if not media.is_media or not candidate_items:
            return matches

        log_p = media.logical_path.lower()
        log_dir = os.path.dirname(log_p)
        media_stem = os.path.splitext(log_p)[0]
        fn_lower = media.filename.lower()
        fn_stem = os.path.splitext(fn_lower)[0]

        json_cands = [j for j in candidate_items if j.is_json and j.is_safe]
        matched_json_keys: Set[str] = set()

        # 1. 全檔名 P1
        p1_key = log_p + ".json"
        for j in json_cands:
            if j.logical_path.lower() == p1_key or j.filename.lower() == (fn_lower + ".json"):
                matched_json_keys.add(j.source_key)
                matches.append(SidecarMatch(media, j, "EXACT_FULL_PATH", "全檔名精準配對"))

        # 2. Supplemental Metadata P2
        p2_suffixes = [".supplemental-metadata.json", ".supplemental-metada.json", ".supplemental-meta.json", ".supplemental.json"]
        for j in json_cands:
            if j.source_key in matched_json_keys:
                continue
            j_log = j.logical_path.lower()
            if any(j_log == (log_p + suf) for suf in p2_suffixes) or any(j.filename.lower() == (fn_lower + suf) for suf in p2_suffixes):
                matched_json_keys.add(j.source_key)
                matches.append(SidecarMatch(media, j, "EXACT_FULL_PATH_SUPPLEMENTAL", "Supplemental Metadata 配對"))

        # 3. 裸 stem P3 (需要檢查同目錄是否有相片檔保護 Live Photo 影片)
        has_sibling_photo = False
        if media.extension in EXT_VIDEOS:
            for item in candidate_items:
                if item != media and item.is_media and item.extension in EXT_PHOTOS:
                    if os.path.splitext(item.logical_path.lower())[0] == media_stem:
                        has_sibling_photo = True
                        break

        if not has_sibling_photo:
            p3_key = media_stem + ".json"
            for j in json_cands:
                if j.source_key in matched_json_keys:
                    continue
                j_log = j.logical_path.lower()
                stem_parsed, _ = cls._extract_json_stem(j_log)
                if j_log == p3_key or j.filename.lower() == (fn_stem + ".json") or stem_parsed.lower() == media_stem:
                    matched_json_keys.add(j.source_key)
                    matches.append(SidecarMatch(media, j, "BASE_STEM", "裸 stem 配對"))

        # 4. Takeout 重複編號變體 P4
        m_num = re.search(r'^(.*?)(\(\d+\))$', fn_stem)
        if m_num:
            raw_base, num_part = m_num.group(1), m_num.group(2)
            p4_cands = [
                f"{raw_base}{media.extension}{num_part}.json",
                f"{fn_stem}{media.extension}.json",
                f"{fn_stem}.json"
            ]
            for j in json_cands:
                if j.source_key in matched_json_keys:
                    continue
                j_fn = j.filename.lower()
                if any(j_fn == cand.lower() for cand in p4_cands):
                    matched_json_keys.add(j.source_key)
                    matches.append(SidecarMatch(media, j, "NUMBERED_VARIANT", "Google Takeout 重複編號變體配對"))

        return matches

    @classmethod
    def match_sources(cls, items: List[SourceItem]) -> MatchOutcome:
        """
        對輸入的 SourceItem 列表進行全域階段式 (Phase-by-Phase) 優先序 Sidecar 配對。
        規則：
        1. 全域階段式執行：所有媒體統一完畢 P1 才能推進至 P2，依此類推，絕不讓低優先序 (P6) 搶走別人的高優先序 (P1-P5) 候選。
        2. 一個 JSON 最多賦予給一個媒體。
        3. 比較時不區分大小寫，但輸出保留原始物件名稱。
        4. 優先序階段：
           - Phase 1 (P1): 同封存檔/同目錄、全媒體檔名 + .json (photo.jpg ↔ photo.jpg.json)
           - Phase 2 (P2): 同封存檔/同目錄、Supplemental Metadata 及其截斷變體
           - Phase 3 (P3): 同封存檔/同目錄、裸 stem + .json (photo.jpg ↔ photo.json)
           - Phase 4 (P4): 同封存檔/同目錄、Google Takeout 重複編號變體 (photo(1).jpg ↔ photo.jpg(1).json)
           - Phase 5 (P5): 跨 ZIP / 跨封存檔、相同邏輯路徑配對 (CROSS_ZIP_EXACT)
           - Phase 6 (P6): 跨資料夾檔名備用配對 (僅在全任務候選嚴格唯一時生效)
        5. 同階段若有多個候選，標記 AMBIGUOUS，結果決定性排序。
        """
        outcome = MatchOutcome()
        if not items:
            return outcome

        media_items: List[SourceItem] = []
        json_items: List[SourceItem] = []

        for item in items:
            if not item.is_safe:
                continue
            if item.is_json:
                json_items.append(item)
            elif item.is_media:
                media_items.append(item)

        # 預先建立同目錄相片 stem 快速查詢集合 (完全消除 Phase 3 的 O(n²) 媒體×媒體重複掃描)
        photo_stems_by_dir: Dict[str, Set[str]] = {}
        for m in media_items:
            if m.extension in EXT_PHOTOS:
                d = os.path.dirname(m.logical_path.lower())
                s = os.path.splitext(m.logical_path.lower())[0]
                if d not in photo_stems_by_dir:
                    photo_stems_by_dir[d] = set()
                photo_stems_by_dir[d].add(s)

        # 建立快速尋找對照表
        json_by_logical_path: Dict[str, List[SourceItem]] = {}
        json_by_stem_path: Dict[str, List[SourceItem]] = {}
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

        # 決定性排序
        media_items.sort(key=lambda x: x.source_key)
        active_media: List[SourceItem] = list(media_items)

        def get_unassigned(cands: List[SourceItem]) -> List[SourceItem]:
            return [c for c in cands if c.source_key not in assigned_json_keys and c.source_key not in ambiguous_json_keys]

        # -------------------------------------------------------------
        # Phase 1 (P1): 同封存檔/同目錄、全媒體檔名 + .json
        # -------------------------------------------------------------
        next_active: List[SourceItem] = []
        for media in active_media:
            log_p = media.logical_path.lower()
            p1_key = log_p + ".json"
            if p1_key in json_by_logical_path:
                cands = [c for c in json_by_logical_path[p1_key] if cls.is_same_archive(media, c)]
                valid_cands = get_unassigned(cands)
                if len(valid_cands) == 1:
                    assigned_json_keys.add(valid_cands[0].source_key)
                    outcome.matched_pairs.append(SidecarMatch(
                        media_item=media,
                        json_item=valid_cands[0],
                        match_quality="EXACT_FULL_PATH",
                        reason="同封存檔全檔名精準配對 (.jpg.json)"
                    ))
                    continue
                elif len(valid_cands) > 1:
                    outcome.ambiguous_media.append(media)
                    for c in valid_cands:
                        ambiguous_json_keys.add(c.source_key)
                    continue
            next_active.append(media)
        active_media = next_active

        # -------------------------------------------------------------
        # Phase 2 (P2): 同封存檔/同目錄、Supplemental Metadata 及其截斷變體
        # -------------------------------------------------------------
        next_active = []
        for media in active_media:
            log_p = media.logical_path.lower()
            p2_candidates = [
                log_p + ".supplemental-metadata.json",
                log_p + ".supplemental-metada.json",
                log_p + ".supplemental-meta.json",
                log_p + ".supplemental.json",
            ]
            matched_flag = False
            for p2_key in p2_candidates:
                if p2_key in json_by_logical_path:
                    cands = [c for c in json_by_logical_path[p2_key] if cls.is_same_archive(media, c)]
                    valid_cands = get_unassigned(cands)
                    if len(valid_cands) == 1:
                        assigned_json_keys.add(valid_cands[0].source_key)
                        outcome.matched_pairs.append(SidecarMatch(
                            media_item=media,
                            json_item=valid_cands[0],
                            match_quality="EXACT_FULL_PATH_SUPPLEMENTAL",
                            reason="同封存檔 Supplemental Metadata 配對"
                        ))
                        matched_flag = True
                        break
                    elif len(valid_cands) > 1:
                        outcome.ambiguous_media.append(media)
                        for c in valid_cands:
                            ambiguous_json_keys.add(c.source_key)
                        matched_flag = True
                        break
            if not matched_flag:
                next_active.append(media)
        active_media = next_active

        # -------------------------------------------------------------
        # Phase 3 (P3): 同封存檔/同目錄、裸 stem + .json (O(1) 集合尋找)
        # -------------------------------------------------------------
        next_active = []
        for media in active_media:
            log_p = media.logical_path.lower()
            log_dir = os.path.dirname(log_p)
            media_stem = os.path.splitext(log_p)[0]
            p3_key = media_stem + ".json"

            if p3_key in json_by_logical_path or p3_key in json_by_stem_path:
                raw_cands = json_by_logical_path.get(p3_key, []) + json_by_stem_path.get(p3_key, [])
                unique_cands = {c.source_key: c for c in raw_cands if cls.is_same_archive(media, c)}
                valid_cands = get_unassigned(list(unique_cands.values()))

                # Live Photo 保護：若是影片且同目錄有相片檔 stem 存在，O(1) 精準跳過不搶奪裸 stem.json
                if media.extension in EXT_VIDEOS:
                    if media_stem in photo_stems_by_dir.get(log_dir, set()):
                        valid_cands = []

                if len(valid_cands) == 1:
                    assigned_json_keys.add(valid_cands[0].source_key)
                    outcome.matched_pairs.append(SidecarMatch(
                        media_item=media,
                        json_item=valid_cands[0],
                        match_quality="BASE_STEM",
                        reason="同封存檔裸 stem 配對 (.json)"
                    ))
                    continue
                elif len(valid_cands) > 1:
                    outcome.ambiguous_media.append(media)
                    for c in valid_cands:
                        ambiguous_json_keys.add(c.source_key)
                    continue
            next_active.append(media)
        active_media = next_active

        # -------------------------------------------------------------
        # Phase 4 (P4): 同封存檔/同目錄、Google Takeout 重複編號變體
        # -------------------------------------------------------------
        next_active = []
        for media in active_media:
            log_p = media.logical_path.lower()
            log_dir = os.path.dirname(log_p)
            fn_stem = os.path.splitext(media.filename.lower())[0]
            m_num = re.search(r'^(.*?)(\(\d+\))$', fn_stem)

            matched_flag = False
            if m_num:
                raw_base, num_part = m_num.group(1), m_num.group(2)
                p4_candidates = [
                    os.path.join(log_dir, f"{raw_base}{media.extension}{num_part}.json").replace('\\', '/').strip('/'),
                    os.path.join(log_dir, f"{fn_stem}{media.extension}.json").replace('\\', '/').strip('/'),
                    os.path.join(log_dir, f"{fn_stem}.json").replace('\\', '/').strip('/'),
                ]
                for p4_key in p4_candidates:
                    if p4_key in json_by_logical_path:
                        cands = [c for c in json_by_logical_path[p4_key] if cls.is_same_archive(media, c)]
                        valid_cands = get_unassigned(cands)
                        if len(valid_cands) == 1:
                            assigned_json_keys.add(valid_cands[0].source_key)
                            outcome.matched_pairs.append(SidecarMatch(
                                media_item=media,
                                json_item=valid_cands[0],
                                match_quality="NUMBERED_VARIANT",
                                reason="Google Takeout 重複編號變體配對"
                            ))
                            matched_flag = True
                            break
                        elif len(valid_cands) > 1:
                            outcome.ambiguous_media.append(media)
                            for c in valid_cands:
                                ambiguous_json_keys.add(c.source_key)
                            matched_flag = True
                            break
            if not matched_flag:
                next_active.append(media)
        active_media = next_active

        # -------------------------------------------------------------
        # Phase 5 (P5): 跨 ZIP / 跨封存檔相同邏輯路徑配對 (CROSS_ZIP_EXACT)
        # -------------------------------------------------------------
        next_active = []
        for media in active_media:
            log_p = media.logical_path.lower()
            p5_key = log_p + ".json"
            if p5_key in json_by_logical_path:
                cands = [c for c in json_by_logical_path[p5_key] if not cls.is_same_archive(media, c)]
                valid_cands = get_unassigned(cands)
                if len(valid_cands) == 1:
                    assigned_json_keys.add(valid_cands[0].source_key)
                    outcome.matched_pairs.append(SidecarMatch(
                        media_item=media,
                        json_item=valid_cands[0],
                        match_quality="CROSS_ZIP_EXACT",
                        reason="跨 ZIP 相同邏輯路徑配對"
                    ))
                    continue
                elif len(valid_cands) > 1:
                    outcome.ambiguous_media.append(media)
                    for c in valid_cands:
                        ambiguous_json_keys.add(c.source_key)
                    continue
            next_active.append(media)
        active_media = next_active

        # -------------------------------------------------------------
        # Phase 6 (P6): 跨資料夾檔名備用配對 (全任務候選嚴格唯一時生效)
        # -------------------------------------------------------------
        next_active = []
        for media in active_media:
            fn_lower = media.filename.lower()
            fn_stem = os.path.splitext(fn_lower)[0]
            p6_fn_keys = [
                (fn_lower + ".json"),
                (fn_lower + ".supplemental-metadata.json"),
                (fn_stem + ".json")
            ]
            matched_flag = False
            for p6_key in p6_fn_keys:
                if p6_key in json_by_filename:
                    valid_cands = get_unassigned(json_by_filename[p6_key])
                    if len(valid_cands) == 1:
                        assigned_json_keys.add(valid_cands[0].source_key)
                        outcome.matched_pairs.append(SidecarMatch(
                            media_item=media,
                            json_item=valid_cands[0],
                            match_quality="FILENAME_MATCH",
                            reason="跨目錄單一檔名備用配對"
                        ))
                        matched_flag = True
                        break
                    elif len(valid_cands) > 1:
                        outcome.ambiguous_media.append(media)
                        for c in valid_cands:
                            ambiguous_json_keys.add(c.source_key)
                        matched_flag = True
                        break
            if not matched_flag:
                next_active.append(media)

        # 整理未配對媒體與 JSON
        outcome.unmatched_media = list(next_active)
        for j in json_items:
            if j.source_key in ambiguous_json_keys:
                outcome.ambiguous_json.append(j)
            elif j.source_key not in assigned_json_keys:
                outcome.unmatched_json.append(j)

        # 決定性排序所有輸出
        outcome.matched_pairs.sort(key=lambda x: x.media_item.source_key)
        outcome.unmatched_media.sort(key=lambda x: x.source_key)
        outcome.unmatched_json.sort(key=lambda x: x.source_key)
        outcome.ambiguous_media.sort(key=lambda x: x.source_key)
        outcome.ambiguous_json.sort(key=lambda x: x.source_key)

        return outcome
