# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 2 - MediaGroup 與 Live Photo 配對模組 (media_group.py)
定義不可拆分的 MediaGroup 資料模型、GroupMember 角色分派與 MediaGroupBuilder 配對引擎。
"""

import os
import re
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple
from source_index import SourceItem
from sidecar_matcher import SidecarMatcher, MatchOutcome, SidecarMatch
from media_types import EXT_PHOTOS, EXT_VIDEOS


class GroupRole:
    PRIMARY = "PRIMARY"
    GOOGLE_JSON = "GOOGLE_JSON"
    LIVE_PHOTO_VIDEO = "LIVE_PHOTO_VIDEO"
    RAW_PAIR = "RAW_PAIR"
    AUXILIARY = "AUXILIARY"


@dataclass
class GroupMember:
    source_item: SourceItem
    role: str
    db_member_id: Optional[int] = None


@dataclass
class MediaGroup:
    group_id: str
    primary_media: SourceItem
    source_type: str                  # "FOLDER" 或 "TAKEOUT_ZIP"
    members: List[GroupMember] = field(default_factory=list)
    capture_date: Optional[str] = None
    date_source: Optional[str] = None
    date_confidence: Optional[int] = None
    status: str = "DISCOVERED"        # "DISCOVERED", "PAIRED", "VALIDATED", "CONFLICT"


class MediaGroupBuilder:
    """MediaGroup 建立器與 Live Photo / RAW / Sidecar 配對引擎"""

    @classmethod
    def build_groups(
        cls,
        source_items: List[SourceItem],
        sidecar_outcome: Optional[MatchOutcome] = None
    ) -> List[MediaGroup]:
        """
        對輸入的 SourceItem 列表進行 Live Photo、RAW/JPEG 與 Sidecar 配對，建立不拆分的 MediaGroup 列表。
        規則：
        1. 若未傳入 sidecar_outcome，自動使用 SidecarMatcher.match_sources(source_items) 進行配對。
        2. 相同邏輯目錄/ZIP、相同檔案 stem 的相片 (HEIC/JPG) 與影片 (MOV/MP4) 綁定為 Live Photo MediaGroup，影片標記為 LIVE_PHOTO_VIDEO。
        3. RAW 與 JPEG (例如 .cr3 + .jpg) 綁定為同一 MediaGroup，次要檔標記為 RAW_PAIR。
        4. 配對到的 Sidecar JSON 併入相同的 MediaGroup，標記為 GOOGLE_JSON。
        5. 其餘獨立媒體建立單成員的 MediaGroup。
        """
        if not source_items:
            return []

        if sidecar_outcome is None:
            sidecar_outcome = SidecarMatcher.match_sources(source_items)

        # Sidecar 對照表：media.source_key -> List[json SourceItem]
        matched_json_by_media: Dict[str, List[SourceItem]] = {}
        for match in sidecar_outcome.matched_pairs:
            m_key = match.media_item.source_key
            if m_key not in matched_json_by_media:
                matched_json_by_media[m_key] = []
            matched_json_by_media[m_key].append(match.json_item)

        # 整理媒體與 JSON 條目
        media_items = [i for i in source_items if i.is_media and i.is_safe]
        
        # 已綁定媒體集合
        assigned_media_keys: Set[str] = set()
        groups: List[MediaGroup] = []

        # 按邏輯目錄 + 小寫 stem 分流
        # (log_dir, stem_lower) -> List[SourceItem]
        stem_groups: Dict[Tuple[str, str], List[SourceItem]] = {}
        for m in media_items:
            log_p = m.logical_path.lower()
            d = os.path.dirname(log_p)
            s = os.path.splitext(os.path.basename(log_p))[0]
            base_s = re.sub(r'\(\d+\)$', '', s)
            key = (d, base_s)
            if key not in stem_groups:
                stem_groups[key] = []
            stem_groups[key].append(m)

        # 決定性排序
        sorted_keys = sorted(stem_groups.keys())

        for key in sorted_keys:
            items_in_stem = stem_groups[key]
            unassigned_in_stem = [m for m in items_in_stem if m.source_key not in assigned_media_keys]
            if not unassigned_in_stem:
                continue

            photos = [m for m in unassigned_in_stem if m.extension in EXT_PHOTOS]
            videos = [m for m in unassigned_in_stem if m.extension in EXT_VIDEOS]

            # 情況 A: 同 stem 包含相片與影片 ➔ 建立 Live Photo MediaGroup
            if photos and videos:
                primary = photos[0]
                gid = f"mg_{primary.source_key.replace(':', '_')}"

                group_members = [GroupMember(primary, GroupRole.PRIMARY)]
                assigned_media_keys.add(primary.source_key)

                for p in photos[1:]:
                    role = GroupRole.RAW_PAIR if (primary.extension in ('.raw', '.arw', '.cr2', '.cr3', '.dng', '.nef') or p.extension in ('.raw', '.arw', '.cr2', '.cr3', '.dng', '.nef')) else GroupRole.AUXILIARY
                    group_members.append(GroupMember(p, role))
                    assigned_media_keys.add(p.source_key)

                for v in videos:
                    group_members.append(GroupMember(v, GroupRole.LIVE_PHOTO_VIDEO))
                    assigned_media_keys.add(v.source_key)

                for m_item in photos + videos:
                    jsons = matched_json_by_media.get(m_item.source_key, [])
                    for j in jsons:
                        if not any(gm.source_item.source_key == j.source_key for gm in group_members):
                            group_members.append(GroupMember(j, GroupRole.GOOGLE_JSON))

                mg = MediaGroup(
                    group_id=gid,
                    primary_media=primary,
                    source_type=primary.source_type,
                    members=group_members,
                    status="PAIRED"
                )
                groups.append(mg)

            # 情況 B: 同 stem 包含多個相片 (例如 RAW + JPEG 組合)
            elif len(photos) > 1:
                raw_photos = [p for p in photos if p.extension in ('.raw', '.arw', '.cr2', '.cr3', '.dng', '.nef')]
                primary = raw_photos[0] if raw_photos else photos[0]
                gid = f"mg_{primary.source_key.replace(':', '_')}"

                group_members = [GroupMember(primary, GroupRole.PRIMARY)]
                assigned_media_keys.add(primary.source_key)

                for p in photos:
                    if p.source_key == primary.source_key:
                        continue
                    group_members.append(GroupMember(p, GroupRole.RAW_PAIR))
                    assigned_media_keys.add(p.source_key)

                for p in photos:
                    jsons = matched_json_by_media.get(p.source_key, [])
                    for j in jsons:
                        if not any(gm.source_item.source_key == j.source_key for gm in group_members):
                            group_members.append(GroupMember(j, GroupRole.GOOGLE_JSON))

                mg = MediaGroup(
                    group_id=gid,
                    primary_media=primary,
                    source_type=primary.source_type,
                    members=group_members,
                    status="PAIRED"
                )
                groups.append(mg)

            # 情況 C: 獨立單一媒體 (未綁定 Live Photo 或 RAW/JPEG)
            else:
                for m in unassigned_in_stem:
                    if m.source_key in assigned_media_keys:
                        continue
                    gid = f"mg_{m.source_key.replace(':', '_')}"
                    group_members = [GroupMember(m, GroupRole.PRIMARY)]
                    assigned_media_keys.add(m.source_key)

                    jsons = matched_json_by_media.get(m.source_key, [])
                    for j in jsons:
                        group_members.append(GroupMember(j, GroupRole.GOOGLE_JSON))

                    status = "PAIRED" if jsons else "DISCOVERED"
                    mg = MediaGroup(
                        group_id=gid,
                        primary_media=m,
                        source_type=m.source_type,
                        members=group_members,
                        status=status
                    )
                    groups.append(mg)

        groups.sort(key=lambda x: x.group_id)
        return groups
