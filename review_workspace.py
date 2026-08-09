# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 3 - Review Workspace 與捷徑安全邊界。

SQLite 是審核狀態的唯一權威來源；Windows `.lnk` 只供人工瀏覽。
本模組不搬移、不刪除、不改名任何來源媒體。
"""

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple

from import_state import TakeoutStateManager
from media_types import EXT_MEDIA


REVIEW_CATEGORIES: Dict[str, str] = {
    "DUPLICATE": "01_重複照片",
    "SIMILAR": "02_相似照片",
    "BLURRY": "03_模糊照片",
    "SCREENSHOT": "04_螢幕截圖",
    "SHORT_VIDEO": "05_短影片",
    "DATE_ANOMALY": "06_日期異常",
}
PENDING_DELETE_DIRECTORY = "99_待刪除"
REVIEW_ROOT_NAME = "_Review"
REVIEW_CACHE_NAME = "_ReviewCache"


class ShortcutBackend(Protocol):
    """Windows 捷徑建立／解析介面，便於沿用現有 WinShellReader 與單元測試。"""

    def create_shortcut(self, link_path: str, target_path: str) -> bool:
        ...

    def resolve_shortcut(self, link_path: str) -> Optional[str]:
        ...


@dataclass
class ReviewEntry:
    review_entry_id: str
    job_id: str
    group_id: str
    category: str
    score: Optional[float]
    reason: Optional[str]
    shortcut_path: str
    target_path: str
    cache_path: Optional[str]
    status: str
    error_msg: Optional[str] = None


class ReviewWorkspaceError(RuntimeError):
    """Review Workspace 建立、捷徑或安全驗證失敗。"""


class ReviewWorkspaceManager:
    """建立 ReviewEntry、管理 `_Review` 目錄並驗證已登記捷徑。"""

    ENTRY_ID_PATTERN = re.compile(r"^(re_[0-9a-f]{24})__", re.IGNORECASE)
    INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    TERMINAL_STATUSES = {"SELECTED", "QUARANTINED"}

    def __init__(
        self,
        state_manager: TakeoutStateManager,
        shortcut_backend: ShortcutBackend,
        destination_root: str,
        allowed_source_roots: Optional[List[str]] = None,
        dry_run: bool = False,
    ):
        self.state_manager = state_manager
        self.shortcut_backend = shortcut_backend
        self.destination_root = self._absolute(destination_root)
        self.review_root = os.path.join(self.destination_root, REVIEW_ROOT_NAME)
        self.cache_root = os.path.join(self.destination_root, REVIEW_CACHE_NAME)
        self.allowed_source_roots = [
            self._absolute(root)
            for root in (allowed_source_roots or [])
            if root
        ]
        self.dry_run = dry_run

    @staticmethod
    def _absolute(path: str) -> str:
        return os.path.abspath(os.path.normpath(path))

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

    @classmethod
    def _safe_filename(cls, filename: str, max_length: int = 100) -> str:
        cleaned = cls.INVALID_FILENAME_CHARS.sub("_", filename).strip(" .")
        if not cleaned:
            cleaned = "media"
        return cleaned[:max_length].rstrip(" .") or "media"

    @staticmethod
    def _safe_id_component(value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", value or ""):
            return value
        digest = hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:24]
        return f"id_{digest}"

    @staticmethod
    def _entry_id(job_id: str, group_id: str, category: str) -> str:
        payload = f"{job_id}\n{group_id}\n{category}".encode("utf-8")
        return f"re_{hashlib.sha256(payload).hexdigest()[:24]}"

    def initialize(self) -> Dict[str, str]:
        """建立固定 Review 目錄骨架並回傳各分類絕對路徑。"""
        paths = {
            code: os.path.join(self.review_root, folder_name)
            for code, folder_name in REVIEW_CATEGORIES.items()
        }
        paths["PENDING_DELETE"] = os.path.join(
            self.review_root,
            PENDING_DELETE_DIRECTORY,
        )
        if not self.dry_run:
            os.makedirs(self.cache_root, exist_ok=True)
            for path in paths.values():
                os.makedirs(path, exist_ok=True)
        return paths

    def cache_directory_for(self, job_id: str, group_id: str) -> str:
        """取得單一 ZIP MediaGroup 專屬 ReviewCache 路徑，不主動實體化媒體。"""
        return os.path.join(
            self.cache_root,
            self._safe_id_component(job_id),
            self._safe_id_component(group_id),
        )

    def _target_is_allowed(self, target_path: str) -> bool:
        roots = [self.cache_root] + self.allowed_source_roots
        return any(self._is_within(target_path, root) for root in roots)

    def _entry_from_record(self, record: Dict[str, object]) -> ReviewEntry:
        return ReviewEntry(
            review_entry_id=str(record["review_entry_id"]),
            job_id=str(record["job_id"]),
            group_id=str(record["group_id"]),
            category=str(record["category"]),
            score=record.get("score"),
            reason=record.get("reason"),
            shortcut_path=str(record["shortcut_path"]),
            target_path=str(record["target_path"]),
            cache_path=record.get("cache_path"),
            status=str(record["status"]),
            error_msg=record.get("error_msg"),
        )

    def register_review(
        self,
        job_id: str,
        group_id: str,
        category: str,
        target_path: str,
        score: Optional[float] = None,
        reason: Optional[str] = None,
        cache_path: Optional[str] = None,
        display_filename: Optional[str] = None,
    ) -> ReviewEntry:
        """建立一筆 ReviewEntry 與零覆寫 `.lnk`；JSON 不允許單獨建立捷徑。"""
        if category not in REVIEW_CATEGORIES:
            raise ValueError(f"不支援的審核分類: {category}")

        target_path = self._absolute(target_path)
        if os.path.splitext(target_path)[1].lower() not in EXT_MEDIA:
            raise ReviewWorkspaceError("審核捷徑只能指向媒體，不可指向 JSON 或其他檔案")
        if not os.path.isfile(target_path):
            raise ReviewWorkspaceError(f"審核目標不存在或不是檔案: {target_path}")
        if not self._target_is_allowed(target_path):
            raise ReviewWorkspaceError("審核目標超出允許的來源或 ReviewCache 範圍")

        group = self.state_manager.get_media_group(group_id)
        if not group or group["job_id"] != job_id:
            raise ReviewWorkspaceError("MediaGroup 不存在或不屬於目前 Job")

        self.initialize()
        review_entry_id = self._entry_id(job_id, group_id, category)
        filename = self._safe_filename(display_filename or os.path.basename(target_path))
        shortcut_path = os.path.join(
            self.review_root,
            REVIEW_CATEGORIES[category],
            f"{review_entry_id}__{filename}.lnk",
        )
        cache_path = self._absolute(cache_path) if cache_path else None
        if cache_path:
            expected_cache_path = self.cache_directory_for(job_id, group_id)
            if self._canonical(cache_path) != self._canonical(expected_cache_path):
                raise ReviewWorkspaceError("ReviewCache 路徑與目前 Job／MediaGroup 不一致")
            if not self._is_within(target_path, cache_path):
                raise ReviewWorkspaceError("ZIP 審核媒體不在已登記的 MediaGroup 快取目錄內")

        preview_entry = ReviewEntry(
            review_entry_id=review_entry_id,
            job_id=job_id,
            group_id=group_id,
            category=category,
            score=score,
            reason=reason,
            shortcut_path=shortcut_path,
            target_path=target_path,
            cache_path=cache_path,
            status="PREVIEW" if self.dry_run else "PENDING",
        )
        if self.dry_run:
            return preview_entry

        existing = self.state_manager.get_review_entry(review_entry_id)
        if existing and existing["status"] in self.TERMINAL_STATUSES:
            return self._entry_from_record(existing)

        self.state_manager.upsert_review_entry(
            review_entry_id=review_entry_id,
            job_id=job_id,
            group_id=group_id,
            category=category,
            score=score,
            reason=reason,
            shortcut_path=shortcut_path,
            target_path=target_path,
            cache_path=cache_path,
            status="PENDING",
        )

        temp_link = os.path.join(
            os.path.dirname(shortcut_path),
            f".{review_entry_id}.{uuid.uuid4().hex}.part.lnk",
        )
        try:
            if os.path.exists(shortcut_path):
                resolved = self.shortcut_backend.resolve_shortcut(shortcut_path)
                if resolved and self._canonical(resolved) == self._canonical(target_path):
                    self.state_manager.update_review_entry_status(review_entry_id, "READY")
                    record = self.state_manager.get_review_entry(review_entry_id)
                    return self._entry_from_record(record)
                raise ReviewWorkspaceError("審核捷徑已存在但指向不同目標，禁止覆寫")

            if not self.shortcut_backend.create_shortcut(temp_link, target_path):
                raise ReviewWorkspaceError("Windows 捷徑建立失敗")
            if not os.path.isfile(temp_link):
                raise ReviewWorkspaceError("捷徑後端回報成功，但暫存捷徑不存在")

            os.rename(temp_link, shortcut_path)
            self.state_manager.update_review_entry_status(review_entry_id, "READY")
        except Exception as exc:
            if (
                os.path.isfile(temp_link)
                and not os.path.islink(temp_link)
                and self._is_within(temp_link, self.review_root)
            ):
                try:
                    os.remove(temp_link)
                except OSError:
                    pass
            error_message = str(exc)
            self.state_manager.update_review_entry_status(
                review_entry_id,
                "ERROR",
                error_message,
            )
            if isinstance(exc, ReviewWorkspaceError):
                raise
            raise ReviewWorkspaceError(error_message) from exc

        record = self.state_manager.get_review_entry(review_entry_id)
        return self._entry_from_record(record)

    def validate_registered_shortcut(
        self,
        shortcut_path: str,
    ) -> Tuple[bool, Optional[ReviewEntry], Optional[str]]:
        """解析 `.lnk` 並同時核對 Review 根目錄、SQLite 登記與允許目標範圍。"""
        shortcut_path = self._absolute(shortcut_path)
        if not self._is_within(shortcut_path, self.review_root):
            return False, None, "捷徑不在受管理的 _Review 目錄內"
        if os.path.splitext(shortcut_path)[1].lower() != ".lnk":
            return False, None, "檔案不是 Windows .lnk 捷徑"

        match = self.ENTRY_ID_PATTERN.match(os.path.basename(shortcut_path))
        if not match:
            return False, None, "捷徑檔名缺少已登記的 ReviewEntry ID"
        record = self.state_manager.get_review_entry(match.group(1).lower())
        if not record:
            return False, None, "SQLite 找不到對應的 ReviewEntry"

        resolved = self.shortcut_backend.resolve_shortcut(shortcut_path)
        if not resolved:
            return False, None, "無法解析捷徑目標"
        if self._canonical(resolved) != self._canonical(str(record["target_path"])):
            return False, None, "捷徑目標與 SQLite 登記不一致"
        if not self._target_is_allowed(resolved):
            return False, None, "捷徑目標超出允許範圍"
        if not os.path.isfile(resolved):
            return False, None, "捷徑目標不存在或不是檔案"
        return True, self._entry_from_record(record), None
