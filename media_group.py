# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 2 - MediaGroup 與 Live Photo 配對模組。

本模組只建立記憶體資料模型，不搬移、不刪除、不改名來源檔案。
"""

import hashlib
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from media_types import (
    JPEG_PHOTO_EXTENSIONS,
    LIVE_PHOTO_IMAGE_EXTENSIONS,
    LIVE_PHOTO_VIDEO_EXTENSIONS,
    RAW_PHOTO_EXTENSIONS,
)
from sidecar_matcher import MatchOutcome, SidecarMatcher
from source_index import SourceItem


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
    source_type: str
    members: List[GroupMember] = field(default_factory=list)
    capture_date: Optional[str] = None
    date_source: Optional[str] = None
    date_confidence: Optional[int] = None
    date_conflict: bool = False
    status: str = "DISCOVERED"


class LivePhotoPairer:
    """Live Photo 格式關係判斷器。"""

    @staticmethod
    def is_live_photo_pair(first: SourceItem, second: SourceItem) -> bool:
        extensions = {first.extension.lower(), second.extension.lower()}
        return bool(
            extensions & LIVE_PHOTO_IMAGE_EXTENSIONS
            and extensions & LIVE_PHOTO_VIDEO_EXTENSIONS
        )


class MediaGroupBuilder:
    """建立 Live Photo、RAW/JPEG 與 Sidecar 的不可拆分 MediaGroup。"""

    @staticmethod
    def _media_sort_key(item: SourceItem) -> Tuple[int, str]:
        """RAW 優先作為主媒體，其次為 HEIC、JPEG、影片及其他格式。"""
        ext = item.extension.lower()
        if ext in RAW_PHOTO_EXTENSIONS:
            priority = 0
        elif ext == ".heic":
            priority = 1
        elif ext in JPEG_PHOTO_EXTENSIONS:
            priority = 2
        elif ext in LIVE_PHOTO_VIDEO_EXTENSIONS:
            priority = 3
        else:
            priority = 4
        return priority, item.source_key

    @staticmethod
    def _is_raw_jpeg_pair(first: SourceItem, second: SourceItem) -> bool:
        first_ext = first.extension.lower()
        second_ext = second.extension.lower()
        return (
            first_ext in RAW_PHOTO_EXTENSIONS
            and second_ext in JPEG_PHOTO_EXTENSIONS
        ) or (
            second_ext in RAW_PHOTO_EXTENSIONS
            and first_ext in JPEG_PHOTO_EXTENSIONS
        )

    @classmethod
    def _connected_components(cls, items: List[SourceItem]) -> List[List[SourceItem]]:
        """只依明確 Live Photo 或 RAW/JPEG 關係建立連通群組。"""
        adjacency: Dict[str, Set[str]] = {item.source_key: set() for item in items}
        by_key = {item.source_key: item for item in items}
        ordered = sorted(items, key=lambda item: item.source_key)

        for index, first in enumerate(ordered):
            for second in ordered[index + 1:]:
                if (
                    LivePhotoPairer.is_live_photo_pair(first, second)
                    or cls._is_raw_jpeg_pair(first, second)
                ):
                    adjacency[first.source_key].add(second.source_key)
                    adjacency[second.source_key].add(first.source_key)

        components: List[List[SourceItem]] = []
        visited: Set[str] = set()
        for item in ordered:
            if item.source_key in visited:
                continue
            stack = [item.source_key]
            component: List[SourceItem] = []
            while stack:
                current_key = stack.pop()
                if current_key in visited:
                    continue
                visited.add(current_key)
                component.append(by_key[current_key])
                stack.extend(sorted(adjacency[current_key], reverse=True))
            components.append(sorted(component, key=cls._media_sort_key))
        return components

    @staticmethod
    def _make_group_id(component: List[SourceItem], job_id: Optional[str]) -> str:
        """建立穩定雜湊 ID；Sidecar 變動不會改變 MediaGroup 主鍵。"""
        identities = []
        for item in component:
            if item.source_type == "FOLDER" and item.abs_path:
                identity = os.path.normcase(os.path.abspath(item.abs_path))
            else:
                identity = item.source_key
            identities.append(identity)
        payload = "\n".join([job_id or ""] + sorted(identities))
        return f"mg_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _append_sidecars(
        group_members: List[GroupMember],
        component: List[SourceItem],
        matched_json_by_media: Dict[str, List[SourceItem]],
    ) -> None:
        existing_keys = {member.source_item.source_key for member in group_members}
        for media_item in sorted(component, key=lambda item: item.source_key):
            sidecars = sorted(
                matched_json_by_media.get(media_item.source_key, []),
                key=lambda item: item.source_key,
            )
            for json_item in sidecars:
                if json_item.source_key not in existing_keys:
                    group_members.append(GroupMember(json_item, GroupRole.GOOGLE_JSON))
                    existing_keys.add(json_item.source_key)

    @classmethod
    def build_groups(
        cls,
        source_items: List[SourceItem],
        sidecar_outcome: Optional[MatchOutcome] = None,
        job_id: Optional[str] = None,
    ) -> List[MediaGroup]:
        """
        建立 MediaGroup。

        配對限定在相同來源類型、相同 ZIP 指紋、相同邏輯目錄及完全相同 stem。
        僅 HEIC/JPEG + MOV/MP4 視為 Live Photo；僅 RAW + JPEG 視為 RAW 配對。
        """
        if not source_items:
            return []

        if sidecar_outcome is None:
            sidecar_outcome = SidecarMatcher.match_sources(
                source_items,
                allow_multiple_per_media=True,
            )

        matched_json_by_media: Dict[str, List[SourceItem]] = {}
        for match in sidecar_outcome.matched_pairs:
            matched_json_by_media.setdefault(match.media_item.source_key, []).append(
                match.json_item
            )

        media_items = [item for item in source_items if item.is_media and item.is_safe]
        stem_groups: Dict[Tuple[str, str, str, str], List[SourceItem]] = {}
        for media_item in media_items:
            logical_path = media_item.logical_path.replace("\\", "/").lower()
            logical_directory = os.path.dirname(logical_path)
            exact_stem = os.path.splitext(os.path.basename(logical_path))[0]
            archive_scope = (
                media_item.archive_fingerprint or ""
                if media_item.source_type == "TAKEOUT_ZIP"
                else ""
            )
            key = (
                media_item.source_type,
                archive_scope,
                logical_directory,
                exact_stem,
            )
            stem_groups.setdefault(key, []).append(media_item)

        groups: List[MediaGroup] = []
        for key in sorted(stem_groups):
            items = sorted(stem_groups[key], key=cls._media_sort_key)
            for component in cls._connected_components(items):
                primary = component[0]
                group_members = [GroupMember(primary, GroupRole.PRIMARY)]
                has_raw = any(
                    item.extension.lower() in RAW_PHOTO_EXTENSIONS
                    for item in component
                )

                for media_item in component[1:]:
                    ext = media_item.extension.lower()
                    if ext in LIVE_PHOTO_VIDEO_EXTENSIONS and any(
                        LivePhotoPairer.is_live_photo_pair(media_item, candidate)
                        for candidate in component
                    ):
                        role = GroupRole.LIVE_PHOTO_VIDEO
                    elif has_raw and ext in JPEG_PHOTO_EXTENSIONS:
                        role = GroupRole.RAW_PAIR
                    else:
                        role = GroupRole.AUXILIARY
                    group_members.append(GroupMember(media_item, role))

                cls._append_sidecars(
                    group_members,
                    component,
                    matched_json_by_media,
                )
                groups.append(MediaGroup(
                    group_id=cls._make_group_id(component, job_id),
                    primary_media=primary,
                    source_type=primary.source_type,
                    members=group_members,
                    status="PAIRED" if len(group_members) > 1 else "DISCOVERED",
                ))

        groups.sort(key=lambda group: group.group_id)
        return groups
