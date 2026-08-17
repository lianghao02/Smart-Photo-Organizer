# -*- coding: utf-8 -*-
"""v3.0 Phase 9－MediaGroup 整組日期歸檔與崩潰恢復。"""

import datetime
import hashlib
import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .import_state import TakeoutStateManager
from .media_types import EXT_PHOTOS
from .quarantine_manager import (
    DEFAULT_FREE_SPACE_RESERVE,
    QuarantineError,
    QuarantineManager,
)
from .review_workspace import PENDING_DELETE_DIRECTORY, ReviewWorkspaceManager
from .source_index import is_reparse_point_or_link


DATE_CONFIDENCE_THRESHOLD = 50
ARCHIVE_TERMINAL_STATUSES = {"ARCHIVED", "QUARANTINED"}
RESERVED_DESTINATION_NAMES = {
    "_Review",
    "_ReviewCache",
    "_Quarantine",
    "_ImportTemp",
}


class ArchiveError(RuntimeError):
    """日期歸檔規劃、驗證或交易失敗。"""


@dataclass
class ArchiveSummary:
    dry_run: bool
    planned_group_count: int = 0
    completed_group_count: int = 0
    skipped_group_count: int = 0
    planned_bytes: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    destination_directories: List[str] = field(default_factory=list)


class MediaArchiveManager(QuarantineManager):
    """沿用已驗證的兩階段複製／SHA-256／移除流程進行日期歸檔。"""

    def __init__(
        self,
        state_manager: TakeoutStateManager,
        review_workspace: ReviewWorkspaceManager,
        destination_root: str,
        dry_run: bool = True,
        free_space_reserve: int = DEFAULT_FREE_SPACE_RESERVE,
        date_confidence_threshold: int = DATE_CONFIDENCE_THRESHOLD,
    ):
        super().__init__(
            state_manager,
            review_workspace,
            destination_root,
            dry_run=dry_run,
            free_space_reserve=free_space_reserve,
        )
        self.archive_root = os.path.abspath(destination_root)
        self.date_confidence_threshold = max(
            0,
            min(100, int(date_confidence_threshold)),
        )

    @staticmethod
    def _action_id(job_id: str, group_id: str) -> str:
        payload = f"{job_id}\n{group_id}".encode("utf-8")
        return f"ar_{hashlib.sha256(payload).hexdigest()[:24]}"

    @staticmethod
    def _parse_capture_date(value: object) -> datetime.datetime:
        if not value or not isinstance(value, str):
            raise ArchiveError("缺少可歸檔的拍攝日期")
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ArchiveError(f"拍攝日期格式無法解析: {value}") from exc

    @staticmethod
    def _primary_member(group: Dict[str, object]) -> Dict[str, object]:
        members = list(group.get("members") or [])
        for member in members:
            if member.get("role") == "PRIMARY":
                return member
        if members:
            return members[0]
        raise ArchiveError("MediaGroup 沒有任何成員")

    def _destination_directory(
        self,
        group: Dict[str, object],
        resolved_paths: Dict[str, str],
    ) -> Tuple[str, str]:
        capture_date = self._parse_capture_date(group.get("capture_date"))
        if bool(group.get("date_conflict")):
            raise ArchiveError("日期仍有衝突，必須先完成 06_日期異常人工審核")
        confidence = group.get("date_confidence")
        if confidence is None or int(confidence) < self.date_confidence_threshold:
            raise ArchiveError(
                f"日期可信度未達 {self.date_confidence_threshold} 分，禁止自動歸檔"
            )
        primary = self._primary_member(group)
        primary_key = str(primary["source_key"])
        primary_path = resolved_paths.get(primary_key)
        if not primary_path:
            raise ArchiveError("找不到 MediaGroup 主要媒體路徑")
        extension = os.path.splitext(primary_path)[1].lower()
        media_folder = "Photos" if extension in EXT_PHOTOS else "Videos"
        destination_dir = os.path.join(
            self.archive_root,
            capture_date.strftime("%Y"),
            capture_date.strftime("%m"),
            media_folder,
        )
        if any(
            os.path.normcase(part) == os.path.normcase(reserved)
            for part in os.path.relpath(destination_dir, self.archive_root).split(os.sep)
            for reserved in RESERVED_DESTINATION_NAMES
        ):
            raise ArchiveError("日期歸檔目的路徑落入保留工作目錄")
        return destination_dir, os.path.splitext(os.path.basename(primary_path))[0]

    @staticmethod
    def _apply_group_suffix(filename: str, primary_stem: str, suffix: str) -> str:
        if filename.casefold().startswith(primary_stem.casefold()):
            boundary = len(primary_stem)
            if len(filename) == boundary or filename[boundary] == ".":
                return filename[:boundary] + suffix + filename[boundary:]
        stem, extension = os.path.splitext(filename)
        return f"{stem}{suffix}{extension}"

    def _choose_destination_paths(
        self,
        destination_dir: str,
        source_paths: Dict[str, str],
        primary_stem: str,
        group_id: str,
    ) -> Dict[str, str]:
        ordered_keys = sorted(source_paths)

        def build(suffix: str) -> Dict[str, str]:
            result: Dict[str, str] = {}
            used = set()
            for source_key in ordered_keys:
                filename = os.path.basename(source_paths[source_key])
                candidate = self._apply_group_suffix(filename, primary_stem, suffix)
                canonical_name = candidate.casefold()
                if canonical_name in used:
                    stem, extension = os.path.splitext(candidate)
                    key_suffix = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:8]
                    candidate = f"{stem}__{key_suffix}{extension}"
                    canonical_name = candidate.casefold()
                used.add(canonical_name)
                result[source_key] = os.path.join(destination_dir, candidate)
            return result

        destinations = build("")
        if len({path.casefold() for path in destinations.values()}) == len(destinations) and not any(
            os.path.exists(path) for path in destinations.values()
        ):
            return destinations

        stable = hashlib.sha256(group_id.encode("utf-8")).hexdigest()[:8]
        for sequence in range(10000):
            suffix = f"__{stable}" if sequence == 0 else f"__{stable}_{sequence:03d}"
            destinations = build(suffix)
            if len({path.casefold() for path in destinations.values()}) != len(destinations):
                continue
            if not any(os.path.exists(path) for path in destinations.values()):
                return destinations
        raise ArchiveError("無法為 MediaGroup 取得零覆寫目的檔名")

    def _safe_remove_part(self, part_path: str, destination_path: str) -> None:
        if part_path != destination_path + ".part":
            raise ArchiveError("暫存檔路徑不符合日期歸檔目的檔")
        if not self._is_within(part_path, self.archive_root):
            raise ArchiveError("暫存檔超出日期歸檔目標根目錄")
        if is_reparse_point_or_link(part_path):
            raise ArchiveError("拒絕清理 Reparse Point／Symlink 暫存檔")
        if os.path.isfile(part_path):
            os.remove(part_path)

    def _pending_delete_groups(self, job_id: str, summary: ArchiveSummary) -> set:
        pending_dir = os.path.join(
            self.review_workspace.review_root,
            PENDING_DELETE_DIRECTORY,
        )
        groups = set()
        if not os.path.isdir(pending_dir):
            return groups
        for filename in sorted(os.listdir(pending_dir)):
            if os.path.splitext(filename)[1].lower() != ".lnk":
                continue
            path = os.path.join(pending_dir, filename)
            valid, entry, error = self.review_workspace.validate_registered_shortcut(
                path,
                require_target_exists=False,
            )
            if not valid or not entry:
                summary.warnings.append(f"忽略無效待刪除捷徑 [{filename}]: {error}")
                continue
            if entry.job_id == job_id:
                groups.add(entry.group_id)
        return groups

    def _plan_action(
        self,
        job_id: str,
        group: Dict[str, object],
        resolved_paths: Dict[str, str],
        summary: ArchiveSummary,
    ) -> Tuple[str, str, List[Dict[str, object]]]:
        group_id = str(group["group_id"])
        source_type = str(group["source_type"])
        destination_dir, primary_stem = self._destination_directory(
            group,
            resolved_paths,
        )
        required_keys = [str(member["source_key"]) for member in group["members"]]
        missing = [key for key in required_keys if not resolved_paths.get(key)]
        if missing:
            raise ArchiveError(
                "MediaGroup 成員路徑不完整，禁止部分歸檔: "
                + ", ".join(sorted(missing))
            )
        sources: Dict[str, str] = {}
        canonical_sources = set()
        for source_key in required_keys:
            source_path = os.path.abspath(resolved_paths[source_key])
            if not os.path.isfile(source_path):
                raise ArchiveError(f"來源成員不存在或不是檔案: {source_path}")
            if is_reparse_point_or_link(source_path):
                raise ArchiveError(f"拒絕歸檔 Reparse Point／Symlink: {source_path}")
            if not self._source_path_allowed(source_path, source_type, job_id, group_id):
                raise ArchiveError(f"來源成員超出允許範圍: {source_path}")
            canonical = self._canonical(source_path)
            if canonical in canonical_sources:
                raise ArchiveError(f"MediaGroup 重複指向同一實體來源: {source_path}")
            canonical_sources.add(canonical)
            sources[source_key] = source_path

        destinations = self._choose_destination_paths(
            destination_dir,
            sources,
            primary_stem,
            group_id,
        )
        items: List[Dict[str, object]] = []
        for source_key in sorted(sources):
            source_path = sources[source_key]
            size = os.path.getsize(source_path)
            digest = self._sha256(source_path)
            summary.planned_bytes += size
            items.append({
                "source_key": source_key,
                "source_path": source_path,
                "destination_path": destinations[source_key],
                "file_size": size,
                "sha256": digest,
                "status": "PLANNED",
            })
        return self._action_id(job_id, group_id), destination_dir, items

    def _cleanup_group_links(
        self,
        job_id: str,
        group_id: str,
        summary: ArchiveSummary,
    ) -> None:
        if not os.path.isdir(self.review_workspace.review_root):
            return
        for directory_name in os.listdir(self.review_workspace.review_root):
            directory = os.path.join(self.review_workspace.review_root, directory_name)
            if not os.path.isdir(directory) or is_reparse_point_or_link(directory):
                continue
            for filename in os.listdir(directory):
                if os.path.splitext(filename)[1].lower() != ".lnk":
                    continue
                link_path = os.path.join(directory, filename)
                valid, entry, _ = self.review_workspace.validate_registered_shortcut(
                    link_path,
                    require_target_exists=False,
                )
                if valid and entry and entry.job_id == job_id and entry.group_id == group_id:
                    try:
                        os.remove(link_path)
                    except OSError as exc:
                        summary.warnings.append(f"已歸檔但無法清除審核捷徑: {exc}")

    def archive_groups(
        self,
        job_id: str,
        resolved_group_paths: Dict[str, Dict[str, str]],
        group_ids: Optional[Iterable[str]] = None,
    ) -> ArchiveSummary:
        """依拍攝年月將完整 MediaGroup 交易式歸檔；預設只產生 DRY_RUN。"""
        summary = ArchiveSummary(dry_run=self.dry_run)
        selected_ids = set(group_ids) if group_ids is not None else None
        pending_delete = self._pending_delete_groups(job_id, summary)

        for group in self.state_manager.list_media_groups(job_id):
            group_id = str(group["group_id"])
            if selected_ids is not None and group_id not in selected_ids:
                continue
            if str(group.get("status")) == "QUARANTINED":
                summary.skipped_group_count += 1
                continue
            if group_id in pending_delete:
                summary.skipped_group_count += 1
                summary.warnings.append(
                    f"{group_id}: 尚在 99_待刪除，請先處理 Quarantine"
                )
                continue

            action_id = self._action_id(job_id, group_id)
            existing = self.state_manager.get_archive_action(action_id)
            if existing and existing["status"] == "COMPLETED":
                summary.skipped_group_count += 1
                if not self.dry_run:
                    self.state_manager.update_media_group_status(
                        job_id,
                        group_id,
                        "ARCHIVED",
                    )
                    self._cleanup_group_links(job_id, group_id, summary)
                continue

            destination_dir: Optional[str] = None
            try:
                if existing and existing.get("items"):
                    destination_dir = str(existing["destination_dir"])
                    items = list(existing["items"])
                    summary.planned_bytes += sum(int(item["file_size"]) for item in items)
                else:
                    action_id, destination_dir, items = self._plan_action(
                        job_id,
                        group,
                        resolved_group_paths.get(group_id, {}),
                        summary,
                    )
                summary.planned_group_count += 1
                summary.destination_directories.append(destination_dir)
                if self.dry_run:
                    continue

                required_space = sum(
                    int(item["file_size"])
                    for item in items
                    if not os.path.isfile(str(item["destination_path"]))
                )
                free_space = shutil.disk_usage(self.archive_root).free
                if free_space < required_space + self.free_space_reserve:
                    raise ArchiveError(
                        f"歸檔空間不足：需要 {required_space + self.free_space_reserve} 位元組，"
                        f"目前可用 {free_space} 位元組"
                    )

                self.state_manager.upsert_archive_action(
                    action_id,
                    job_id,
                    group_id,
                    str(group["source_type"]),
                    destination_dir,
                    status="COPYING",
                )
                if not existing or not existing.get("items"):
                    for item in items:
                        self.state_manager.upsert_archive_item(
                            action_id,
                            str(item["source_key"]),
                            str(item["source_path"]),
                            str(item["destination_path"]),
                            int(item["file_size"]),
                            str(item["sha256"]),
                        )

                # 第一階段：完整群組全部複製、fsync、容量與 SHA-256 驗證。
                for item in items:
                    self._copy_and_verify(item)
                    self.state_manager.update_archive_item_status(
                        action_id,
                        str(item["source_key"]),
                        "COPIED",
                    )
                self.state_manager.upsert_archive_action(
                    action_id,
                    job_id,
                    group_id,
                    str(group["source_type"]),
                    destination_dir,
                    status="REMOVING_SOURCE",
                )

                # 第二階段：整組目的檔皆驗證後，才逐檔移除來源。
                for item in items:
                    self._remove_verified_source(
                        item,
                        str(group["source_type"]),
                        job_id,
                        group_id,
                    )
                    self.state_manager.update_archive_item_status(
                        action_id,
                        str(item["source_key"]),
                        "COMPLETED",
                    )

                self.state_manager.upsert_archive_action(
                    action_id,
                    job_id,
                    group_id,
                    str(group["source_type"]),
                    destination_dir,
                    status="COMPLETED",
                )
                self.state_manager.update_group_review_status(
                    job_id,
                    group_id,
                    "ARCHIVED",
                )
                self.state_manager.update_media_group_status(
                    job_id,
                    group_id,
                    "ARCHIVED",
                )
                self._cleanup_group_links(job_id, group_id, summary)
                summary.completed_group_count += 1
            except Exception as exc:
                message = str(exc)
                summary.errors.append(f"{group_id}: {message}")
                if not self.dry_run and (existing or destination_dir):
                    try:
                        self.state_manager.upsert_archive_action(
                            action_id,
                            job_id,
                            group_id,
                            str(group["source_type"]),
                            destination_dir or str(existing["destination_dir"]),
                            status="FAILED",
                            error_msg=message,
                        )
                    except Exception:
                        pass
        return summary
