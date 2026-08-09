# -*- coding: utf-8 -*-
"""Smart-Photo-Organizer v3.0 分析、審核、隔離與日期歸檔協調器。"""

import datetime
import hashlib
import os
import shutil
import uuid
import zlib
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from archive_manager import ArchiveSummary, MediaArchiveManager
from date_review import (
    DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    DateAnomalyReviewer,
    DateReviewTarget,
)
from import_state import JobType, TakeoutState, TakeoutStateManager
from media_group import GroupRole, MediaGroup, MediaGroupBuilder
from media_metadata import MediaMetadataExtractor
from media_types import EXT_PHOTOS
from quarantine_manager import QuarantineManager, QuarantineSummary
from review_classifier import MediaAnalysisTarget, ReviewClassifier
from review_workspace import ReviewWorkspaceManager
from sidecar_matcher import SidecarMatcher
from similarity import (
    SimilarPhotoDetector,
    SimilarityCandidate,
    SimilarityFingerprint,
)
from source_index import (
    FolderSourceIndexer,
    SourceItem,
    TakeoutSourceIndexer,
    is_reparse_point_or_link,
)
from takeout_zip import TakeoutZipScanner


V3_DB_RELATIVE_PATH = os.path.join("_ImportTemp", "v3_state.db")
MAX_SIDECAR_BYTES = 10 * 1024 * 1024
HASH_BLOCK_SIZE = 1024 * 1024


class PipelineCancelled(RuntimeError):
    """使用者要求停止目前任務。"""


@dataclass
class AnalysisOptions:
    screenshot_enabled: bool = True
    blur_enabled: bool = True
    short_video_enabled: bool = True
    similar_enabled: bool = True


@dataclass
class AnalysisSummary:
    job_id: str
    resumed_job: bool = False
    source_item_count: int = 0
    media_group_count: int = 0
    reviewed_group_count: int = 0
    cached_group_count: int = 0
    category_counts: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    date_audit_path: Optional[str] = None


@dataclass
class _JobContext:
    job_id: str
    source_mode: str
    items: List[SourceItem]
    items_by_key: Dict[str, SourceItem]
    groups: List[MediaGroup]
    groups_by_id: Dict[str, MediaGroup]


class V3Pipeline:
    """單次只實體化一個 Takeout MediaGroup，非審核候選立即清理。"""

    def __init__(
        self,
        source_path: str,
        destination_root: str,
        source_mode: str,
        shortcut_backend,
        date_parser,
        shell_reader=None,
        log_callback: Optional[Callable[[str, str], None]] = None,
        progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        if source_mode not in {"folder", "takeout_zip"}:
            raise ValueError(f"不支援的來源模式: {source_mode}")
        self.source_path = os.path.abspath(source_path)
        self.destination_root = os.path.abspath(destination_root)
        self.source_mode = source_mode
        if self.source_mode == "folder" and not os.path.isdir(self.source_path):
            raise ValueError("一般資料夾模式的來源必須是資料夾")
        if self.source_mode == "takeout_zip" and not (
            os.path.isdir(self.source_path)
            or (
                os.path.isfile(self.source_path)
                and self.source_path.lower().endswith(".zip")
            )
        ):
            raise ValueError("Takeout 模式的來源必須是 ZIP 或包含 ZIP 的資料夾")
        self.date_parser = date_parser
        self.shell_reader = shell_reader
        self.log_callback = log_callback or (lambda message, level="info": None)
        self.progress_callback = progress_callback or (lambda data: None)
        self.cancel_check = cancel_check or (lambda: False)
        self.state = TakeoutStateManager(
            os.path.join(self.destination_root, V3_DB_RELATIVE_PATH)
        )
        allowed_roots = [self.source_path] if os.path.isdir(self.source_path) else [
            os.path.dirname(self.source_path)
        ]
        self.workspace = ReviewWorkspaceManager(
            self.state,
            shortcut_backend,
            self.destination_root,
            allowed_source_roots=allowed_roots,
        )
        self._context: Optional[_JobContext] = None

    def _log(self, message: str, level: str = "info") -> None:
        self.log_callback(message, level)

    def _check_cancel(self) -> None:
        if self.cancel_check():
            raise PipelineCancelled("使用者停止任務")

    def _zip_paths(self) -> List[str]:
        if os.path.isfile(self.source_path):
            return [self.source_path] if self.source_path.lower().endswith(".zip") else []
        paths: List[str] = []
        for root, dirs, files in os.walk(self.source_path, topdown=True, followlinks=False):
            dirs[:] = [
                name for name in dirs
                if not is_reparse_point_or_link(os.path.join(root, name))
            ]
            for filename in files:
                if filename.lower().endswith(".zip"):
                    path = os.path.join(root, filename)
                    if not is_reparse_point_or_link(path):
                        paths.append(path)
        paths.sort(key=lambda path: os.path.normcase(os.path.abspath(path)))
        if len(paths) > TakeoutZipScanner.MAX_ZIP_COUNT:
            raise ValueError(
                f"ZIP 數量超過上限: {len(paths)} > {TakeoutZipScanner.MAX_ZIP_COUNT}"
            )
        return paths

    def _index_items(self) -> List[SourceItem]:
        if self.source_mode == "folder":
            return FolderSourceIndexer.index_folder(self.source_path)
        zip_paths = self._zip_paths()
        if not zip_paths:
            raise ValueError("來源中找不到可讀取的 Google Takeout ZIP")
        items = TakeoutSourceIndexer.index_archives(zip_paths)
        if len(items) > TakeoutZipScanner.MAX_JOB_TOTAL_MEMBERS:
            raise ValueError(
                "ZIP 任務成員總數超過安全上限: "
                f"{len(items):,} > {TakeoutZipScanner.MAX_JOB_TOTAL_MEMBERS:,}"
            )
        return items

    def close(self) -> None:
        """釋放目前管線持有的 Windows Shell 背景程序。"""
        if self.shell_reader and hasattr(self.shell_reader, "stop"):
            try:
                self.shell_reader.stop()
            except Exception:
                pass

    def _new_job_id(self) -> str:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"v3_{stamp}_{uuid.uuid4().hex[:8]}"

    def _build_context(self, job_id: str) -> _JobContext:
        items = self._index_items()
        sidecars = SidecarMatcher.match_sources(items, allow_multiple_per_media=True)
        groups = MediaGroupBuilder.build_groups(items, sidecars, job_id=job_id)
        persisted = {
            record["group_id"]: record
            for record in self.state.list_media_groups(job_id)
        }
        for group in groups:
            record = persisted.get(group.group_id)
            if record:
                group.capture_date = record.get("capture_date")
                group.date_source = record.get("date_source")
                group.date_confidence = record.get("date_confidence")
                group.date_conflict = bool(record.get("date_conflict"))
                group.status = str(record.get("status") or group.status)
        context = _JobContext(
            job_id=job_id,
            source_mode=self.source_mode,
            items=items,
            items_by_key={item.source_key: item for item in items},
            groups=groups,
            groups_by_id={group.group_id: group for group in groups},
        )
        self._context = context
        return context

    def load_latest_context(self) -> Optional[_JobContext]:
        expected_type = "V3_FOLDER" if self.source_mode == "folder" else "V3_TAKEOUT_ZIP"
        latest = self.state.find_latest_job(
            self.source_path,
            self.destination_root,
            job_type=expected_type,
        )
        if not latest:
            return None
        if latest["job_type"] != expected_type:
            return None
        return self._build_context(str(latest["job_id"]))

    @staticmethod
    def _sha256(path: str) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                block = handle.read(HASH_BLOCK_SIZE)
                if not block:
                    break
                hasher.update(block)
        return hasher.hexdigest()

    @staticmethod
    def _crc32(path: str) -> int:
        value = 0
        with open(path, "rb") as handle:
            while True:
                block = handle.read(HASH_BLOCK_SIZE)
                if not block:
                    break
                value = zlib.crc32(block, value)
        return value & 0xFFFFFFFF

    @staticmethod
    def _cache_filename(item: SourceItem, used_names: set) -> str:
        filename = os.path.basename(item.filename)
        candidate = filename
        if candidate.casefold() in used_names:
            stem, extension = os.path.splitext(filename)
            suffix = hashlib.sha256(item.source_key.encode("utf-8")).hexdigest()[:8]
            candidate = f"{stem}__{suffix}{extension}"
        used_names.add(candidate.casefold())
        return candidate

    def _materialize_group(
        self,
        group: MediaGroup,
    ) -> Tuple[Dict[str, str], Dict[str, str], Optional[str]]:
        if group.source_type == "FOLDER":
            paths = {
                member.source_item.source_key: str(member.source_item.abs_path)
                for member in group.members
                if member.source_item.abs_path
            }
            hashes = {
                key: self._sha256(path)
                for key, path in paths.items()
                if os.path.isfile(path)
            }
            return paths, hashes, None

        cache_dir = self.workspace.cache_directory_for(
            self._context.job_id,
            group.group_id,
        )
        os.makedirs(cache_dir, exist_ok=True)
        paths: Dict[str, str] = {}
        hashes: Dict[str, str] = {}
        used_names = set()
        for member in group.members:
            self._check_cancel()
            item = member.source_item
            filename = self._cache_filename(item, used_names)
            destination = os.path.join(cache_dir, filename)
            if not self.workspace._is_within(destination, cache_dir):
                raise ValueError("ReviewCache 成員目的路徑超出群組範圍")
            valid_existing = False
            if os.path.isfile(destination) and not is_reparse_point_or_link(destination):
                try:
                    valid_existing = (
                        os.path.getsize(destination) == item.size
                        and self._crc32(destination) == int(item.member_crc or 0)
                    )
                except OSError:
                    valid_existing = False
            if not valid_existing and os.path.exists(destination):
                if not os.path.isfile(destination) or is_reparse_point_or_link(destination):
                    raise ValueError(f"ReviewCache 既有路徑型態異常: {destination}")
                os.remove(destination)
            if not valid_existing:
                part_path = destination + f".{uuid.uuid4().hex}.part"
                extracted = TakeoutZipScanner.extract_member_stream(
                    zip_path=str(item.archive_path),
                    member_index=int(item.member_index),
                    part_path=part_path,
                    expected_filename=item.archive_member_name or item.logical_path,
                    expected_crc=item.member_crc,
                    expected_size=item.size,
                    cancel_check_func=self.cancel_check,
                )
                actual_part = str(extracted["part_path"])
                try:
                    os.rename(actual_part, destination)
                except FileExistsError:
                    if (
                        os.path.isfile(destination)
                        and os.path.getsize(destination) == item.size
                        and self._crc32(destination) == int(item.member_crc or 0)
                    ):
                        os.remove(actual_part)
                    else:
                        raise
                hashes[item.source_key] = str(extracted["sha256"])
            else:
                hashes[item.source_key] = self._sha256(destination)
            paths[item.source_key] = destination
        return paths, hashes, cache_dir

    def _cleanup_unused_cache(
        self,
        group: MediaGroup,
        paths: Dict[str, str],
        cache_dir: Optional[str],
    ) -> None:
        if group.source_type != "TAKEOUT_ZIP" or not cache_dir:
            return
        expected = self.workspace.cache_directory_for(self._context.job_id, group.group_id)
        if self.workspace._canonical(cache_dir) != self.workspace._canonical(expected):
            raise ValueError("拒絕清理非目前 MediaGroup 的 ReviewCache")
        for path in paths.values():
            if (
                os.path.isfile(path)
                and not is_reparse_point_or_link(path)
                and self.workspace._is_within(path, cache_dir)
            ):
                os.remove(path)
        try:
            os.rmdir(cache_dir)
            parent = os.path.dirname(cache_dir)
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass

    @staticmethod
    def _member_records(group: MediaGroup) -> List[Dict[str, object]]:
        return [
            {
                "member_id": member.db_member_id,
                "source_key": member.source_item.source_key,
                "role": member.role,
            }
            for member in group.members
        ]

    @staticmethod
    def _sidecar_bytes(group: MediaGroup, paths: Dict[str, str]) -> Optional[bytes]:
        for member in group.members:
            if member.role != GroupRole.GOOGLE_JSON:
                continue
            path = paths.get(member.source_item.source_key)
            if not path or not os.path.isfile(path):
                continue
            if os.path.getsize(path) > MAX_SIDECAR_BYTES:
                continue
            with open(path, "rb") as handle:
                return handle.read(MAX_SIDECAR_BYTES + 1)
        return None

    def _resolve_date(
        self,
        group: MediaGroup,
        primary_path: str,
        paths: Dict[str, str],
    ) -> Tuple[Optional[str], str, int, bool, str]:
        sidecar = MediaMetadataExtractor.parse_sidecar_json_bytes(
            self._sidecar_bytes(group, paths)
        )
        google_date = None
        if sidecar and "timestamp" in sidecar:
            google_date = datetime.datetime.fromtimestamp(
                sidecar["timestamp"],
                datetime.timezone.utc,
            ).isoformat()
        details = self.date_parser.get_date_details(
            primary_path,
            is_photo=group.primary_media.extension.lower() in EXT_PHOTOS,
            is_cloud=False,
            shell_reader=self.shell_reader,
            google_json_date=google_date,
        )
        parsed = details.get("date")
        capture_date = parsed.isoformat() if parsed else None
        candidates = " | ".join(
            f"{item.get('source')}={item.get('date')}({item.get('confidence')})"
            for item in details.get("candidates", [])
        )
        return (
            capture_date,
            str(details.get("source") or "無可用日期"),
            int(details.get("confidence") or 0),
            bool(details.get("conflict")),
            candidates,
        )

    @staticmethod
    def _exact_signature(
        group: MediaGroup,
        paths: Dict[str, str],
        hashes: Dict[str, str],
    ) -> Tuple[Tuple[int, str], ...]:
        values = []
        for member in group.members:
            if member.role == GroupRole.GOOGLE_JSON:
                continue
            key = member.source_item.source_key
            path = paths[key]
            values.append((os.path.getsize(path), hashes[key]))
        return tuple(sorted(values))

    def _analysis_target(
        self,
        group: MediaGroup,
        paths: Dict[str, str],
        cache_dir: Optional[str],
    ) -> MediaAnalysisTarget:
        return MediaAnalysisTarget.from_media_group(
            group,
            resolved_paths=paths,
            cache_path=cache_dir,
        )

    def _ensure_group_paths(self, group_id: str) -> Dict[str, str]:
        if not self._context:
            raise ValueError("尚未載入 v3 任務內容")
        group = self._context.groups_by_id.get(group_id)
        if not group:
            raise KeyError(f"找不到 MediaGroup: {group_id}")
        paths, _, _ = self._materialize_group(group)
        return paths

    def analyze(self, options: Optional[AnalysisOptions] = None) -> AnalysisSummary:
        options = options or AnalysisOptions()
        os.makedirs(self.destination_root, exist_ok=True)
        job_type = "V3_FOLDER" if self.source_mode == "folder" else "V3_TAKEOUT_ZIP"
        latest = self.state.find_latest_job(
            self.source_path,
            self.destination_root,
            job_type=job_type,
        )
        resumable_statuses = {
            TakeoutState.CANCELLED,
            TakeoutState.FAILED,
            TakeoutState.COMPLETED_WITH_ERRORS,
        }
        resumed = bool(latest and latest.get("status") in resumable_statuses)
        if resumed:
            job_id = str(latest["job_id"])
            self.state.update_job_status(job_id, "RUNNING")
            self._log(f"↩️ 接續未完成分析任務 {job_id}", "info")
        else:
            job_id = self._new_job_id()
            self.state.create_job(
                job_id,
                job_type,
                self.source_path,
                self.destination_root,
            )
        summary = AnalysisSummary(job_id=job_id, resumed_job=resumed)
        try:
            context = self._build_context(job_id)
            summary.source_item_count = len(context.items)
            summary.media_group_count = len(context.groups)
            self.workspace.initialize()
            immediate_classifier = ReviewClassifier(
                self.workspace,
                screenshot_enabled=options.screenshot_enabled,
                blur_enabled=options.blur_enabled,
                short_video_enabled=options.short_video_enabled,
                similar_enabled=False,
            )
            date_reviewer = DateAnomalyReviewer(self.workspace)
            similarity_detector = SimilarPhotoDetector()
            exact_signatures: Dict[str, object] = {}
            signature_buckets: Dict[object, List[str]] = {}
            similarity_fingerprints: List[SimilarityFingerprint] = []
            date_targets: List[DateReviewTarget] = []
            cached_groups = set()

            for index, group in enumerate(context.groups, start=1):
                self._check_cancel()
                self.progress_callback({
                    "current": index,
                    "total": len(context.groups),
                    "filename": group.primary_media.filename,
                    "stage": "分析 MediaGroup",
                })
                try:
                    paths, hashes, cache_dir = self._materialize_group(group)
                    primary_path = paths[group.primary_media.source_key]
                    (
                        group.capture_date,
                        group.date_source,
                        group.date_confidence,
                        group.date_conflict,
                        candidate_summary,
                    ) = self._resolve_date(group, primary_path, paths)
                    group.status = "ANALYZED"
                    self.state.create_media_group(
                        group.group_id,
                        job_id,
                        None,
                        group.source_type,
                        capture_date=group.capture_date,
                        date_source=group.date_source,
                        date_confidence=group.date_confidence,
                        date_conflict=group.date_conflict,
                        status=group.status,
                        members=self._member_records(group),
                    )
                    target = self._analysis_target(group, paths, cache_dir)
                    immediate = immediate_classifier.classify(job_id, [target])
                    summary.errors.extend(immediate.errors)
                    summary.warnings.extend(immediate.warnings)
                    for entry in immediate.entries:
                        summary.category_counts[entry.category] = (
                            summary.category_counts.get(entry.category, 0) + 1
                        )

                    date_target = DateReviewTarget.from_analysis_target(target)
                    date_target = DateReviewTarget(
                        **{
                            **date_target.__dict__,
                            "candidate_summary": candidate_summary,
                        }
                    )
                    date_targets.append(date_target)
                    date_issue = date_reviewer.issue_for(date_target)

                    signature = self._exact_signature(group, paths, hashes)
                    exact_signatures[group.group_id] = signature
                    signature_buckets.setdefault(signature, []).append(group.group_id)
                    if (
                        options.similar_enabled
                        and group.capture_date
                        and group.primary_media.extension.lower() in EXT_PHOTOS
                    ):
                        try:
                            similarity_fingerprints.append(
                                similarity_detector.fingerprint(SimilarityCandidate(
                                    group.group_id,
                                    primary_path,
                                    group.capture_date,
                                ))
                            )
                        except (OSError, ValueError) as exc:
                            summary.warnings.append(
                                f"{group.group_id}: 略過相似照片指紋 ({exc})"
                            )

                    keep_cache = bool(immediate.entries or date_issue)
                    if keep_cache and cache_dir:
                        cached_groups.add(group.group_id)
                    elif cache_dir:
                        self._cleanup_unused_cache(group, paths, cache_dir)
                except Exception as exc:
                    summary.errors.append(f"{group.group_id}: 分析失敗 ({exc})")

            # 完全重複：只登記決定性排序後的重複副本。
            for signature, group_ids in signature_buckets.items():
                if len(group_ids) < 2:
                    continue
                ordered = sorted(group_ids)
                canonical_id = ordered[0]
                for duplicate_id in ordered[1:]:
                    group = context.groups_by_id[duplicate_id]
                    paths, _, cache_dir = self._materialize_group(group)
                    target = self._analysis_target(group, paths, cache_dir)
                    try:
                        entry = self.workspace.register_review(
                            job_id,
                            duplicate_id,
                            "DUPLICATE",
                            target.primary_path,
                            score=100,
                            reason=f"完整群組 SHA-256 相同；建議保留 {canonical_id}",
                            cache_path=cache_dir,
                            display_filename=target.original_filename,
                        )
                        summary.category_counts["DUPLICATE"] = (
                            summary.category_counts.get("DUPLICATE", 0) + 1
                        )
                        if cache_dir:
                            cached_groups.add(duplicate_id)
                    except Exception as exc:
                        summary.errors.append(f"{duplicate_id}: 重複審核登記失敗 ({exc})")

            if options.similar_enabled:
                similar = similarity_detector.find_similar_fingerprints(
                    similarity_fingerprints,
                    exact_signatures=exact_signatures,
                )
                summary.errors.extend(similar.errors)
                summary.warnings.extend(similar.warnings)
                for group_id, finding in sorted(similar.findings.items()):
                    group = context.groups_by_id[group_id]
                    paths, _, cache_dir = self._materialize_group(group)
                    target = self._analysis_target(group, paths, cache_dir)
                    try:
                        self.workspace.register_review(
                            job_id,
                            group_id,
                            "SIMILAR",
                            target.primary_path,
                            score=finding.score,
                            reason=(
                                f"相似群組 {finding.cluster_id}；"
                                f"參考 {finding.reference_group_id}；"
                                f"dHash 距離 {finding.hamming_distance}"
                            ),
                            cache_path=cache_dir,
                            display_filename=target.original_filename,
                        )
                        summary.category_counts["SIMILAR"] = (
                            summary.category_counts.get("SIMILAR", 0) + 1
                        )
                        if cache_dir:
                            cached_groups.add(group_id)
                    except Exception as exc:
                        summary.errors.append(f"{group_id}: 相似審核登記失敗 ({exc})")

            date_result = date_reviewer.review(job_id, date_targets)
            summary.errors.extend(date_result.errors)
            summary.date_audit_path = date_result.audit_path
            if date_result.entries:
                summary.category_counts["DATE_ANOMALY"] = len(date_result.entries)
                for entry in date_result.entries:
                    if entry.cache_path:
                        cached_groups.add(entry.group_id)

            summary.reviewed_group_count = len({
                record["group_id"]
                for record in self.state.list_review_entries(job_id)
            })
            summary.cached_group_count = len(cached_groups)
            final_status = (
                TakeoutState.COMPLETED_WITH_ERRORS
                if summary.errors else TakeoutState.COMPLETED
            )
            self.state.update_job_status(job_id, final_status)
            return summary
        except PipelineCancelled:
            self.state.update_job_status(job_id, TakeoutState.CANCELLED)
            raise
        except Exception:
            self.state.update_job_status(job_id, TakeoutState.FAILED)
            raise

    def _context_or_latest(self) -> _JobContext:
        if self._context:
            return self._context
        context = self.load_latest_context()
        if not context:
            raise ValueError("找不到可接續的 v3 分析任務，請先執行開始分析")
        return context

    def _resolved_paths(
        self,
        group_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, Dict[str, str]]:
        context = self._context_or_latest()
        selected = set(group_ids) if group_ids is not None else set(context.groups_by_id)
        result = {}
        for group_id in sorted(selected):
            group = context.groups_by_id.get(group_id)
            if not group:
                continue
            paths, _, _ = self._materialize_group(group)
            result[group_id] = paths
        return result

    def _existing_group_paths(self, group: MediaGroup) -> Dict[str, str]:
        """只解析既有來源／ReviewCache，不因 DRY_RUN 額外解壓 ZIP。"""
        if group.source_type == "FOLDER":
            return {
                member.source_item.source_key: str(member.source_item.abs_path)
                for member in group.members
                if member.source_item.abs_path and os.path.isfile(member.source_item.abs_path)
            }
        cache_dir = self.workspace.cache_directory_for(
            self._context.job_id,
            group.group_id,
        )
        used_names = set()
        paths: Dict[str, str] = {}
        for member in group.members:
            filename = self._cache_filename(member.source_item, used_names)
            path = os.path.join(cache_dir, filename)
            if os.path.isfile(path) and not is_reparse_point_or_link(path):
                paths[member.source_item.source_key] = path
        return paths

    def process_pending_delete(self, dry_run: bool = True) -> QuarantineSummary:
        context = self._context_or_latest()
        # 只有位於 99 的群組才需要解析路徑；Manager 仍會再次驗證捷徑。
        preview_manager = QuarantineManager(
            self.state,
            self.workspace,
            self.destination_root,
            dry_run=True,
            free_space_reserve=0,
        )
        discovered = preview_manager._collect_pending_entries(
            context.job_id,
            QuarantineSummary(dry_run=True),
        )
        if dry_run:
            paths = {
                group_id: self._existing_group_paths(context.groups_by_id[group_id])
                for group_id in discovered
                if group_id in context.groups_by_id
            }
        else:
            paths = self._resolved_paths(discovered.keys()) if discovered else {}
        manager = QuarantineManager(
            self.state,
            self.workspace,
            self.destination_root,
            dry_run=dry_run,
        )
        return manager.process_pending(context.job_id, paths)

    def preview_archive(self) -> ArchiveSummary:
        context = self._context_or_latest()
        summary = ArchiveSummary(dry_run=True)
        pending = MediaArchiveManager(
            self.state,
            self.workspace,
            self.destination_root,
            dry_run=True,
        )._pending_delete_groups(context.job_id, summary)
        for group in context.groups:
            record = self.state.get_media_group(group.group_id) or {}
            if str(record.get("status", group.status)) in {"QUARANTINED", "ARCHIVED"}:
                summary.skipped_group_count += 1
                continue
            if group.group_id in pending:
                summary.skipped_group_count += 1
                continue
            if (
                not group.capture_date
                or group.date_conflict
                or group.date_confidence is None
                or int(group.date_confidence) < DEFAULT_LOW_CONFIDENCE_THRESHOLD
            ):
                summary.skipped_group_count += 1
                continue
            summary.planned_group_count += 1
            summary.planned_bytes += sum(
                member.source_item.size for member in group.members
            )
        return summary

    @staticmethod
    def _merge_archive_summary(total: ArchiveSummary, current: ArchiveSummary) -> None:
        total.planned_group_count += current.planned_group_count
        total.completed_group_count += current.completed_group_count
        total.skipped_group_count += current.skipped_group_count
        total.planned_bytes += current.planned_bytes
        total.errors.extend(current.errors)
        total.warnings.extend(current.warnings)
        total.destination_directories.extend(current.destination_directories)

    def archive_by_date(self) -> ArchiveSummary:
        context = self._context_or_latest()
        total = ArchiveSummary(dry_run=False)
        manager = MediaArchiveManager(
            self.state,
            self.workspace,
            self.destination_root,
            dry_run=False,
        )
        pending = manager._pending_delete_groups(context.job_id, total)
        for group in context.groups:
            self._check_cancel()
            record = self.state.get_media_group(group.group_id) or {}
            if (
                str(record.get("status", group.status)) in {"QUARANTINED", "ARCHIVED"}
                or group.group_id in pending
                or not group.capture_date
                or group.date_conflict
                or group.date_confidence is None
                or int(group.date_confidence) < DEFAULT_LOW_CONFIDENCE_THRESHOLD
            ):
                total.skipped_group_count += 1
                continue
            paths = self._resolved_paths([group.group_id])
            current = manager.archive_groups(
                context.job_id,
                paths,
                group_ids=[group.group_id],
            )
            self._merge_archive_summary(total, current)
        return total
