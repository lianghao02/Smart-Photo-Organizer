# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 5 - `99_待刪除` 至 Quarantine 交易管理。

不提供永久刪除。正式執行採兩階段：完整複製並驗證整組後，才逐檔移除來源。
"""

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from import_state import TakeoutStateManager
from review_workspace import (
    PENDING_DELETE_DIRECTORY,
    ReviewEntry,
    ReviewWorkspaceManager,
)
from source_index import is_reparse_point_or_link


QUARANTINE_ROOT_NAME = "_Quarantine"
QUARANTINE_PENDING_NAME = "待刪除"
COPY_BLOCK_SIZE = 1024 * 1024
DEFAULT_FREE_SPACE_RESERVE = 100 * 1024 * 1024


class QuarantineError(RuntimeError):
    """Quarantine 規劃、驗證或交易失敗。"""


@dataclass
class QuarantineSummary:
    dry_run: bool
    discovered_link_count: int = 0
    planned_group_count: int = 0
    completed_group_count: int = 0
    skipped_group_count: int = 0
    planned_bytes: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    destination_directories: List[str] = field(default_factory=list)


class QuarantineManager:
    """只處理已登記且位於 `99_待刪除` 的 ReviewEntry。"""

    def __init__(
        self,
        state_manager: TakeoutStateManager,
        review_workspace: ReviewWorkspaceManager,
        destination_root: str,
        dry_run: bool = True,
        free_space_reserve: int = DEFAULT_FREE_SPACE_RESERVE,
    ):
        self.state_manager = state_manager
        self.review_workspace = review_workspace
        self.destination_root = os.path.abspath(destination_root)
        self.quarantine_root = os.path.join(
            self.destination_root,
            QUARANTINE_ROOT_NAME,
            QUARANTINE_PENDING_NAME,
        )
        self.dry_run = dry_run
        self.free_space_reserve = max(0, int(free_space_reserve))

    @staticmethod
    def _canonical(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    @classmethod
    def _is_within(cls, path: str, root: str) -> bool:
        try:
            return os.path.commonpath([
                cls._canonical(path),
                cls._canonical(root),
            ]) == cls._canonical(root)
        except (OSError, ValueError):
            return False

    @staticmethod
    def _safe_component(value: str) -> str:
        allowed = "".join(
            character
            for character in (value or "")
            if character.isalnum() or character in "_.-"
        )
        if allowed and len(allowed) <= 100:
            return allowed
        digest = hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:24]
        return f"id_{digest}"

    @staticmethod
    def _action_id(job_id: str, group_id: str) -> str:
        payload = f"{job_id}\n{group_id}".encode("utf-8")
        return f"qa_{hashlib.sha256(payload).hexdigest()[:24]}"

    @staticmethod
    def _sha256(path: str) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                block = handle.read(COPY_BLOCK_SIZE)
                if not block:
                    break
                hasher.update(block)
        return hasher.hexdigest()

    def _pending_directory(self) -> str:
        return os.path.join(
            self.review_workspace.review_root,
            PENDING_DELETE_DIRECTORY,
        )

    def _collect_pending_entries(
        self,
        job_id: str,
        summary: QuarantineSummary,
    ) -> Dict[str, List[Tuple[str, ReviewEntry]]]:
        pending_directory = self._pending_directory()
        if not os.path.isdir(pending_directory):
            return {}

        entries_by_group: Dict[str, List[Tuple[str, ReviewEntry]]] = {}
        for filename in sorted(os.listdir(pending_directory)):
            shortcut_path = os.path.join(pending_directory, filename)
            if os.path.splitext(filename)[1].lower() != ".lnk":
                continue
            summary.discovered_link_count += 1
            if is_reparse_point_or_link(shortcut_path):
                summary.errors.append(f"拒絕 Reparse Point／Symlink 捷徑: {shortcut_path}")
                continue
            valid, entry, error = self.review_workspace.validate_registered_shortcut(
                shortcut_path,
                require_target_exists=False,
            )
            if not valid or not entry:
                summary.errors.append(f"捷徑驗證失敗 [{filename}]: {error}")
                continue
            if entry.job_id != job_id:
                summary.errors.append(f"捷徑不屬於目前 Job [{filename}]")
                continue
            if entry.status not in {"READY", "SELECTED", "QUARANTINED"}:
                summary.errors.append(
                    f"ReviewEntry 狀態不可處理 [{filename}]: {entry.status}"
                )
                continue
            entries_by_group.setdefault(entry.group_id, []).append(
                (shortcut_path, entry)
            )
        return entries_by_group

    def _source_path_allowed(
        self,
        source_path: str,
        source_type: str,
        job_id: str,
        group_id: str,
    ) -> bool:
        if self._is_within(source_path, self.quarantine_root):
            return False
        if source_type == "TAKEOUT_ZIP":
            expected_cache = self.review_workspace.cache_directory_for(job_id, group_id)
            return self._is_within(source_path, expected_cache)
        return any(
            self._is_within(source_path, root)
            for root in self.review_workspace.allowed_source_roots
        )

    def _destination_paths(
        self,
        destination_dir: str,
        source_paths: Dict[str, str],
    ) -> Dict[str, str]:
        """保留可讀檔名；同名成員以 source_key 雜湊後綴避免互相覆寫。"""
        destinations: Dict[str, str] = {}
        used_names = set()
        for source_key in sorted(source_paths):
            source_path = source_paths[source_key]
            filename = os.path.basename(source_path)
            candidate = filename
            normalized = candidate.lower()
            sequence = 0
            while normalized in used_names:
                stem, extension = os.path.splitext(filename)
                suffix_payload = f"{source_key}\n{sequence}".encode("utf-8")
                suffix = hashlib.sha256(suffix_payload).hexdigest()[:8]
                candidate = f"{stem}__{suffix}{extension}"
                normalized = candidate.lower()
                sequence += 1
            used_names.add(normalized)
            destinations[source_key] = os.path.join(destination_dir, candidate)
        return destinations

    def _plan_new_action(
        self,
        job_id: str,
        group: Dict[str, object],
        resolved_paths: Dict[str, str],
        summary: QuarantineSummary,
    ) -> Tuple[str, str, List[Dict[str, object]]]:
        group_id = str(group["group_id"])
        source_type = str(group["source_type"])
        action_id = self._action_id(job_id, group_id)
        destination_dir = os.path.join(
            self.quarantine_root,
            self._safe_component(job_id),
            self._safe_component(group_id),
        )

        required_keys = [str(member["source_key"]) for member in group["members"]]
        missing_keys = [key for key in required_keys if not resolved_paths.get(key)]
        if missing_keys:
            raise QuarantineError(
                "MediaGroup 成員路徑不完整，禁止部分隔離: "
                + ", ".join(sorted(missing_keys))
            )

        normalized_sources: Dict[str, str] = {}
        canonical_sources = set()
        for source_key in required_keys:
            source_path = os.path.abspath(resolved_paths[source_key])
            if not os.path.isfile(source_path):
                raise QuarantineError(f"來源成員不存在或不是檔案: {source_path}")
            if is_reparse_point_or_link(source_path):
                raise QuarantineError(f"拒絕隔離 Reparse Point／Symlink: {source_path}")
            if not self._source_path_allowed(
                source_path, source_type, job_id, group_id
            ):
                raise QuarantineError(f"來源成員超出允許範圍: {source_path}")
            canonical_source = self._canonical(source_path)
            if canonical_source in canonical_sources:
                raise QuarantineError(f"MediaGroup 重複指向同一實體來源: {source_path}")
            canonical_sources.add(canonical_source)
            normalized_sources[source_key] = source_path

        destination_paths = self._destination_paths(
            destination_dir,
            normalized_sources,
        )
        items: List[Dict[str, object]] = []
        for source_key in sorted(normalized_sources):
            source_path = normalized_sources[source_key]
            file_size = os.path.getsize(source_path)
            sha256_value = self._sha256(source_path)
            summary.planned_bytes += file_size
            items.append({
                "source_key": source_key,
                "source_path": source_path,
                "destination_path": destination_paths[source_key],
                "file_size": file_size,
                "sha256": sha256_value,
                "status": "PLANNED",
            })
        return action_id, destination_dir, items

    def _safe_remove_part(self, part_path: str, destination_path: str) -> None:
        if part_path != destination_path + ".part":
            raise QuarantineError("暫存檔路徑不符合交易目的檔")
        if not self._is_within(part_path, self.quarantine_root):
            raise QuarantineError("暫存檔超出 Quarantine 範圍")
        if is_reparse_point_or_link(part_path):
            raise QuarantineError("拒絕清理 Reparse Point／Symlink 暫存檔")
        if os.path.isfile(part_path):
            os.remove(part_path)

    def _copy_and_verify(self, item: Dict[str, object]) -> None:
        source_path = str(item["source_path"])
        destination_path = str(item["destination_path"])
        expected_size = int(item["file_size"])
        expected_hash = str(item["sha256"])

        if os.path.isfile(destination_path):
            if (
                os.path.getsize(destination_path) == expected_size
                and self._sha256(destination_path) == expected_hash
            ):
                return
            raise QuarantineError(f"Quarantine 目的檔已存在且內容不同: {destination_path}")
        if not os.path.isfile(source_path):
            raise QuarantineError(
                f"來源與已驗證目的檔皆不存在，無法恢復: {source_path}"
            )

        source_stat = os.stat(source_path)
        if source_stat.st_size != expected_size:
            raise QuarantineError(f"來源容量已改變: {source_path}")
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        part_path = destination_path + ".part"
        if os.path.exists(part_path):
            self._safe_remove_part(part_path, destination_path)

        hasher = hashlib.sha256()
        written = 0
        try:
            with open(source_path, "rb") as source, open(part_path, "xb") as output:
                while True:
                    block = source.read(COPY_BLOCK_SIZE)
                    if not block:
                        break
                    output.write(block)
                    hasher.update(block)
                    written += len(block)
                output.flush()
                os.fsync(output.fileno())

            current_stat = os.stat(source_path)
            if (
                current_stat.st_size != source_stat.st_size
                or current_stat.st_mtime_ns != source_stat.st_mtime_ns
            ):
                raise QuarantineError(f"來源在複製期間被修改: {source_path}")
            if written != expected_size or hasher.hexdigest() != expected_hash:
                raise QuarantineError(f"Quarantine 暫存檔驗證失敗: {source_path}")
            shutil.copystat(source_path, part_path, follow_symlinks=False)
            os.rename(part_path, destination_path)
            if (
                os.path.getsize(destination_path) != expected_size
                or self._sha256(destination_path) != expected_hash
            ):
                raise QuarantineError(f"Quarantine 目的檔落碟驗證失敗: {destination_path}")
        except Exception:
            if os.path.exists(part_path):
                self._safe_remove_part(part_path, destination_path)
            raise

    def _remove_verified_source(
        self,
        item: Dict[str, object],
        source_type: str,
        job_id: str,
        group_id: str,
    ) -> None:
        source_path = str(item["source_path"])
        destination_path = str(item["destination_path"])
        expected_size = int(item["file_size"])
        expected_hash = str(item["sha256"])
        if not os.path.isfile(destination_path):
            raise QuarantineError(f"目的檔不存在，禁止移除來源: {destination_path}")
        if (
            os.path.getsize(destination_path) != expected_size
            or self._sha256(destination_path) != expected_hash
        ):
            raise QuarantineError(f"目的檔驗證不符，禁止移除來源: {destination_path}")
        if not os.path.exists(source_path):
            return
        if not os.path.isfile(source_path) or is_reparse_point_or_link(source_path):
            raise QuarantineError(f"來源型態異常，拒絕移除: {source_path}")
        if not self._source_path_allowed(
            source_path, source_type, job_id, group_id
        ):
            raise QuarantineError(f"來源超出允許範圍，拒絕移除: {source_path}")
        if (
            os.path.getsize(source_path) != expected_size
            or self._sha256(source_path) != expected_hash
        ):
            raise QuarantineError(f"來源內容已改變，拒絕移除: {source_path}")
        os.remove(source_path)

    def _cleanup_processed_links(
        self,
        links: List[Tuple[str, ReviewEntry]],
        summary: QuarantineSummary,
    ) -> None:
        pending_directory = self._pending_directory()
        for shortcut_path, _ in links:
            try:
                if (
                    os.path.isfile(shortcut_path)
                    and not is_reparse_point_or_link(shortcut_path)
                    and os.path.dirname(os.path.abspath(shortcut_path))
                    == os.path.abspath(pending_directory)
                    and os.path.splitext(shortcut_path)[1].lower() == ".lnk"
                ):
                    os.remove(shortcut_path)
            except OSError as exc:
                summary.warnings.append(f"已隔離但無法清除待刪除捷徑: {exc}")

    def process_pending(
        self,
        job_id: str,
        resolved_group_paths: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> QuarantineSummary:
        """
        驗證 `99_待刪除` 後以 group_id 去重並整組隔離。

        `resolved_group_paths` 格式為 `{group_id: {source_key: local_path}}`。
        """
        summary = QuarantineSummary(dry_run=self.dry_run)
        paths_by_group = resolved_group_paths or {}
        pending_entries = self._collect_pending_entries(job_id, summary)

        for group_id in sorted(pending_entries):
            links = pending_entries[group_id]
            group = self.state_manager.get_media_group(group_id)
            if not group or group["job_id"] != job_id:
                summary.errors.append(f"找不到目前 Job 的 MediaGroup: {group_id}")
                continue

            action_id = self._action_id(job_id, group_id)
            existing_action = self.state_manager.get_quarantine_action(action_id)
            if existing_action and existing_action["status"] == "COMPLETED":
                summary.skipped_group_count += 1
                if not self.dry_run:
                    self._cleanup_processed_links(links, summary)
                continue

            try:
                if existing_action and existing_action.get("items"):
                    destination_dir = str(existing_action["destination_dir"])
                    items = existing_action["items"]
                    summary.planned_bytes += sum(int(item["file_size"]) for item in items)
                else:
                    action_id, destination_dir, items = self._plan_new_action(
                        job_id,
                        group,
                        paths_by_group.get(group_id, {}),
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
                free_space = shutil.disk_usage(self.destination_root).free
                if free_space < required_space + self.free_space_reserve:
                    raise QuarantineError(
                        f"Quarantine 空間不足：需要 {required_space + self.free_space_reserve} 位元組，"
                        f"目前可用 {free_space} 位元組"
                    )

                self.state_manager.upsert_quarantine_action(
                    action_id,
                    job_id,
                    group_id,
                    str(group["source_type"]),
                    destination_dir,
                    status="COPYING",
                )
                if not existing_action or not existing_action.get("items"):
                    for item in items:
                        self.state_manager.upsert_quarantine_item(
                            action_id=action_id,
                            source_key=str(item["source_key"]),
                            source_path=str(item["source_path"]),
                            destination_path=str(item["destination_path"]),
                            file_size=int(item["file_size"]),
                            sha256=str(item["sha256"]),
                        )

                # 第一階段：所有成員完整複製並驗證。任何一筆失敗時不移除來源。
                for item in items:
                    self._copy_and_verify(item)
                    self.state_manager.update_quarantine_item_status(
                        action_id,
                        str(item["source_key"]),
                        "COPIED",
                    )
                self.state_manager.upsert_quarantine_action(
                    action_id,
                    job_id,
                    group_id,
                    str(group["source_type"]),
                    destination_dir,
                    status="REMOVING_SOURCE",
                )

                # 第二階段：目的整組已驗證後，才逐檔移除來源以完成「移動」。
                for item in items:
                    self._remove_verified_source(
                        item,
                        str(group["source_type"]),
                        job_id,
                        group_id,
                    )
                    self.state_manager.update_quarantine_item_status(
                        action_id,
                        str(item["source_key"]),
                        "COMPLETED",
                    )

                self.state_manager.upsert_quarantine_action(
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
                    "QUARANTINED",
                )
                self.state_manager.update_media_group_status(
                    job_id,
                    group_id,
                    "QUARANTINED",
                )
                self._cleanup_processed_links(links, summary)
                summary.completed_group_count += 1
            except Exception as exc:
                error_message = str(exc)
                summary.errors.append(f"{group_id}: {error_message}")
                if not self.dry_run:
                    try:
                        self.state_manager.upsert_quarantine_action(
                            action_id,
                            job_id,
                            group_id,
                            str(group["source_type"]),
                            os.path.join(
                                self.quarantine_root,
                                self._safe_component(job_id),
                                self._safe_component(group_id),
                            ),
                            status="FAILED",
                            error_msg=error_message,
                        )
                    except Exception:
                        pass
        return summary
