# -*- coding: utf-8 -*-
"""
Smart-Photo-Organizer v3.0 Phase 4 - 人工審核分類器。

完全重複、模糊與截圖只建立 ReviewEntry／捷徑，不搬移、刪除或改名媒體。
"""

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from media_group import GroupRole, MediaGroup
from media_metadata import MediaMetadataExtractor
from media_types import EXT_MEDIA, EXT_PHOTOS
from review_workspace import ReviewEntry, ReviewWorkspaceManager
from similarity import SimilarPhotoDetector, SimilarityCandidate


HASH_BLOCK_SIZE = 4 * 1024
FULL_HASH_READ_SIZE = 1024 * 1024
SCREENSHOT_SCORE_THRESHOLD = 7
DEFAULT_BLUR_THRESHOLD = 100.0
SHORT_VIDEO_MAX_SECONDS = 5.0
FFPROBE_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class MediaAnalysisTarget:
    """已可讀取的 MediaGroup 分析目標；ZIP 來源必須指向 ReviewCache 或暫存分析檔。"""

    group_id: str
    primary_path: str
    media_paths: Tuple[str, ...] = ()
    cache_path: Optional[str] = None
    original_filename: Optional[str] = None
    contains_live_photo_video: bool = False
    capture_date: Optional[str] = None
    date_source: Optional[str] = None
    date_confidence: Optional[int] = None
    date_conflict: bool = False

    @classmethod
    def from_media_group(
        cls,
        group: MediaGroup,
        resolved_paths: Optional[Dict[str, str]] = None,
        cache_path: Optional[str] = None,
    ) -> "MediaAnalysisTarget":
        """由 MediaGroup 建立本機可讀分析目標；不自行解壓 ZIP。"""
        resolved_paths = resolved_paths or {}

        def resolve_member_path(member) -> Optional[str]:
            item = member.source_item
            return item.abs_path or resolved_paths.get(item.source_key)

        primary_path = (
            group.primary_media.abs_path
            or resolved_paths.get(group.primary_media.source_key)
        )
        if not primary_path:
            raise ValueError("MediaGroup 主要媒體尚無可讀取的本機路徑")

        media_paths = []
        unresolved_members = []
        for member in group.members:
            if member.role == GroupRole.GOOGLE_JSON:
                continue
            path = resolve_member_path(member)
            if path:
                media_paths.append(path)
            else:
                unresolved_members.append(member.source_item.source_key)
        if unresolved_members:
            raise ValueError(
                "MediaGroup 尚有未實體化媒體，禁止以不完整群組進行重複判定: "
                + ", ".join(sorted(unresolved_members))
            )
        if primary_path not in media_paths:
            media_paths.insert(0, primary_path)
        return cls(
            group_id=group.group_id,
            primary_path=primary_path,
            media_paths=tuple(media_paths),
            cache_path=cache_path,
            original_filename=group.primary_media.filename,
            contains_live_photo_video=any(
                member.role == GroupRole.LIVE_PHOTO_VIDEO
                for member in group.members
            ),
            capture_date=group.capture_date,
            date_source=group.date_source,
            date_confidence=group.date_confidence,
            date_conflict=group.date_conflict,
        )

    def all_media_paths(self) -> Tuple[str, ...]:
        paths = self.media_paths or (self.primary_path,)
        canonical_seen = set()
        unique_paths = []
        for path in paths:
            canonical = os.path.normcase(os.path.abspath(path))
            if canonical not in canonical_seen:
                canonical_seen.add(canonical)
                unique_paths.append(path)
        return tuple(unique_paths)


@dataclass
class ClassificationResult:
    entries: List[ReviewEntry] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    analyzed_group_count: int = 0
    similarity_comparison_count: int = 0

    @property
    def category_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.entries:
            counts[entry.category] = counts.get(entry.category, 0) + 1
        return counts


class ExactDuplicateDetector:
    """依群組媒體容量 → partial SHA-256 → full SHA-256 找出完全重複群組。"""

    def __init__(self):
        self._size_cache: Dict[str, int] = {}
        self._file_state_cache: Dict[str, Tuple[int, int]] = {}
        self._partial_cache: Dict[str, str] = {}
        self._full_cache: Dict[str, str] = {}

    @staticmethod
    def _canonical(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def _size(self, path: str) -> int:
        key = self._canonical(path)
        if key not in self._size_cache:
            stat_result = os.stat(path)
            self._size_cache[key] = stat_result.st_size
            self._file_state_cache[key] = (
                stat_result.st_size,
                stat_result.st_mtime_ns,
            )
        else:
            self._assert_unchanged(path)
        return self._size_cache[key]

    def _assert_unchanged(self, path: str) -> None:
        key = self._canonical(path)
        stat_result = os.stat(path)
        current_state = (stat_result.st_size, stat_result.st_mtime_ns)
        expected_state = self._file_state_cache.get(key)
        if expected_state is not None and current_state != expected_state:
            raise OSError("媒體在分析期間已被外部修改，停止使用本次雜湊結果")

    def _partial_hash(self, path: str) -> str:
        key = self._canonical(path)
        if key in self._partial_cache:
            self._assert_unchanged(path)
            return self._partial_cache[key]
        size = self._size(path)
        self._assert_unchanged(path)
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            if size <= HASH_BLOCK_SIZE * 3:
                hasher.update(handle.read())
            else:
                hasher.update(handle.read(HASH_BLOCK_SIZE))
                handle.seek(max(0, size // 2 - HASH_BLOCK_SIZE // 2))
                hasher.update(handle.read(HASH_BLOCK_SIZE))
                handle.seek(-HASH_BLOCK_SIZE, os.SEEK_END)
                hasher.update(handle.read(HASH_BLOCK_SIZE))
        self._assert_unchanged(path)
        result = hasher.hexdigest()
        self._partial_cache[key] = result
        return result

    def _full_hash(self, path: str) -> str:
        key = self._canonical(path)
        if key in self._full_cache:
            self._assert_unchanged(path)
            return self._full_cache[key]
        self._size(path)
        self._assert_unchanged(path)
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                block = handle.read(FULL_HASH_READ_SIZE)
                if not block:
                    break
                hasher.update(block)
        self._assert_unchanged(path)
        result = hasher.hexdigest()
        self._full_cache[key] = result
        return result

    def _group_signature(
        self,
        target: MediaAnalysisTarget,
        hash_kind: str,
    ) -> Tuple[object, ...]:
        paths = target.all_media_paths()
        if hash_kind == "size":
            return tuple(sorted(self._size(path) for path in paths))
        if hash_kind == "partial":
            return tuple(sorted(self._partial_hash(path) for path in paths))
        if hash_kind == "full":
            return tuple(sorted(self._full_hash(path) for path in paths))
        raise ValueError(f"不支援的雜湊階段: {hash_kind}")

    def find_duplicates(
        self,
        targets: Sequence[MediaAnalysisTarget],
    ) -> Tuple[Dict[str, str], List[str]]:
        """回傳 `{重複 group_id: 保留 group_id}` 與檔案讀取錯誤。"""
        errors: List[str] = []
        size_buckets: Dict[Tuple[object, ...], List[MediaAnalysisTarget]] = {}
        for target in sorted(targets, key=lambda item: item.group_id):
            try:
                signature = self._group_signature(target, "size")
                size_buckets.setdefault(signature, []).append(target)
            except OSError as exc:
                errors.append(f"{target.group_id}: 無法讀取媒體容量 ({exc})")

        partial_buckets: Dict[Tuple[object, ...], List[MediaAnalysisTarget]] = {}
        for candidates in size_buckets.values():
            if len(candidates) < 2:
                continue
            for target in candidates:
                try:
                    signature = self._group_signature(target, "partial")
                    partial_buckets.setdefault(signature, []).append(target)
                except OSError as exc:
                    errors.append(f"{target.group_id}: 無法計算部分雜湊 ({exc})")

        duplicates: Dict[str, str] = {}
        for candidates in partial_buckets.values():
            if len(candidates) < 2:
                continue
            full_buckets: Dict[Tuple[object, ...], List[MediaAnalysisTarget]] = {}
            for target in candidates:
                try:
                    signature = self._group_signature(target, "full")
                    full_buckets.setdefault(signature, []).append(target)
                except OSError as exc:
                    errors.append(f"{target.group_id}: 無法計算完整雜湊 ({exc})")
            for exact_matches in full_buckets.values():
                if len(exact_matches) < 2:
                    continue
                ordered = sorted(exact_matches, key=lambda item: item.group_id)
                canonical_group_id = ordered[0].group_id
                for duplicate in ordered[1:]:
                    duplicates[duplicate.group_id] = canonical_group_id
        return duplicates, errors


class OpenCVBlurDetector:
    """OpenCV Laplacian 模糊評估；未安裝選用套件時回傳明確略過原因。"""

    @staticmethod
    def analyze(path: str, threshold: float) -> Tuple[Optional[bool], float, Optional[str]]:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except ImportError:
            return None, 0.0, "未安裝 OpenCV／NumPy，已略過模糊分析"

        try:
            data = np.fromfile(path, np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if image is None:
                return None, 0.0, "OpenCV 無法解碼影像"
            height, width = image.shape[:2]
            if max(height, width) > 1024:
                scale = 1024 / max(height, width)
                image = cv2.resize(
                    image,
                    (int(width * scale), int(height * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            score = float(cv2.Laplacian(image, cv2.CV_64F).var())
            return score < threshold, score, None
        except Exception as exc:
            return None, 0.0, f"模糊分析失敗: {exc}"


class VideoDurationProbe:
    """以唯讀 ffprobe 取得影片長度，不重新編碼或修改媒體。"""

    def __init__(
        self,
        ffprobe_path: Optional[str] = None,
        timeout_seconds: int = FFPROBE_TIMEOUT_SECONDS,
    ):
        self.ffprobe_path = ffprobe_path or os.getenv("FFPROBE_PATH", "ffprobe")
        self.timeout_seconds = max(1, int(timeout_seconds))

    @staticmethod
    def parse_duration(metadata: Dict[str, object]) -> Optional[float]:
        """優先採容器 duration，缺少時取串流中最長的有效 duration。"""
        format_data = metadata.get("format", {})
        if isinstance(format_data, dict):
            try:
                duration = float(format_data.get("duration", 0))
                if duration > 0:
                    return duration
            except (TypeError, ValueError):
                pass
        candidates: List[float] = []
        streams = metadata.get("streams", [])
        if isinstance(streams, list):
            for stream in streams:
                if not isinstance(stream, dict):
                    continue
                try:
                    duration = float(stream.get("duration", 0))
                    if duration > 0:
                        candidates.append(duration)
                except (TypeError, ValueError):
                    continue
        return max(candidates) if candidates else None

    def probe(self, path: str) -> Tuple[Optional[float], Optional[str]]:
        command = [
            self.ffprobe_path,
            "-v", "error",
            "-print_format", "json",
            "-show_entries", "format=duration:stream=duration",
            path,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or f"exit code {result.returncode}"
                return None, f"ffprobe 讀取影片長度失敗: {detail}"
            duration = self.parse_duration(json.loads(result.stdout))
            if duration is None:
                return None, "影片沒有可用的 duration"
            return duration, None
        except FileNotFoundError:
            return None, "找不到 ffprobe，已略過短影片分析"
        except subprocess.TimeoutExpired:
            return None, "ffprobe 讀取影片長度逾時"
        except (json.JSONDecodeError, OSError) as exc:
            return None, f"ffprobe 輸出解析失敗: {exc}"


class ReviewClassifier:
    """執行 Phase 4 三類候選分析，結果只送往 ReviewWorkspace。"""

    def __init__(
        self,
        workspace: ReviewWorkspaceManager,
        duplicate_detector: Optional[ExactDuplicateDetector] = None,
        blur_detector=OpenCVBlurDetector,
        duration_probe: Optional[VideoDurationProbe] = None,
        similarity_detector: Optional[SimilarPhotoDetector] = None,
        screenshot_enabled: bool = True,
        blur_enabled: bool = True,
        short_video_enabled: bool = True,
        similar_enabled: bool = True,
        screenshot_threshold: int = SCREENSHOT_SCORE_THRESHOLD,
        blur_threshold: float = DEFAULT_BLUR_THRESHOLD,
        short_video_max_seconds: float = SHORT_VIDEO_MAX_SECONDS,
    ):
        self.workspace = workspace
        self.duplicate_detector = duplicate_detector or ExactDuplicateDetector()
        self.blur_detector = blur_detector
        self.duration_probe = duration_probe or VideoDurationProbe()
        self.similarity_detector = similarity_detector or SimilarPhotoDetector()
        self.screenshot_enabled = screenshot_enabled
        self.blur_enabled = blur_enabled
        self.short_video_enabled = short_video_enabled
        self.similar_enabled = similar_enabled
        self.screenshot_threshold = screenshot_threshold
        self.blur_threshold = blur_threshold
        self.short_video_max_seconds = max(0.0, float(short_video_max_seconds))

    @staticmethod
    def _deduplicate_targets(
        targets: Iterable[MediaAnalysisTarget],
    ) -> List[MediaAnalysisTarget]:
        by_group: Dict[str, MediaAnalysisTarget] = {}
        for target in targets:
            by_group.setdefault(target.group_id, target)
        return [by_group[group_id] for group_id in sorted(by_group)]

    def classify(
        self,
        job_id: str,
        targets: Iterable[MediaAnalysisTarget],
    ) -> ClassificationResult:
        """分析所有群組並建立 01／03／04 ReviewEntry；任何來源媒體保持原狀。"""
        result = ClassificationResult()
        unique_targets = self._deduplicate_targets(targets)
        result.analyzed_group_count = len(unique_targets)

        duplicates, duplicate_errors = self.duplicate_detector.find_duplicates(unique_targets)
        result.errors.extend(duplicate_errors)

        similar_findings = {}
        if self.similar_enabled:
            similarity_candidates = [
                SimilarityCandidate(
                    group_id=target.group_id,
                    path=target.primary_path,
                    capture_date=target.capture_date,
                )
                for target in unique_targets
                if target.capture_date
                and os.path.splitext(
                    target.original_filename or target.primary_path
                )[1].lower() in EXT_PHOTOS
            ]
            if len(similarity_candidates) >= 2:
                similarity_result = self.similarity_detector.find_similar(
                    similarity_candidates
                )
                similar_findings = similarity_result.findings
                result.errors.extend(similarity_result.errors)
                result.warnings.extend(similarity_result.warnings)
                result.similarity_comparison_count = similarity_result.comparison_count

        blur_unavailable_reported = False
        for target in unique_targets:
            primary_path = os.path.abspath(target.primary_path)
            display_filename = target.original_filename or os.path.basename(primary_path)
            extension = os.path.splitext(display_filename)[1].lower()
            if extension not in EXT_MEDIA or not os.path.isfile(primary_path):
                result.errors.append(f"{target.group_id}: 主要媒體不存在或格式不支援")
                continue

            if target.group_id in duplicates:
                canonical_group = duplicates[target.group_id]
                try:
                    entry = self.workspace.register_review(
                        job_id,
                        target.group_id,
                        "DUPLICATE",
                        primary_path,
                        score=100,
                        reason=f"完整內容雜湊相同；建議保留群組 {canonical_group}",
                        cache_path=target.cache_path,
                        display_filename=display_filename,
                    )
                    result.entries.append(entry)
                except Exception as exc:
                    result.errors.append(f"{target.group_id}: 重複審核登記失敗 ({exc})")

            if target.group_id in similar_findings:
                finding = similar_findings[target.group_id]
                try:
                    entry = self.workspace.register_review(
                        job_id,
                        target.group_id,
                        "SIMILAR",
                        primary_path,
                        score=finding.score,
                        reason=(
                            f"相似群組 {finding.cluster_id}；"
                            f"參考群組 {finding.reference_group_id}；"
                            f"dHash 距離 {finding.hamming_distance}"
                        ),
                        cache_path=target.cache_path,
                        display_filename=display_filename,
                    )
                    result.entries.append(entry)
                except Exception as exc:
                    result.errors.append(f"{target.group_id}: 相似審核登記失敗 ({exc})")

            if self.screenshot_enabled and extension in EXT_PHOTOS:
                score, reasons = MediaMetadataExtractor.calculate_screenshot_score(
                    primary_path,
                    display_filename,
                )
                if score >= self.screenshot_threshold:
                    try:
                        entry = self.workspace.register_review(
                            job_id,
                            target.group_id,
                            "SCREENSHOT",
                            primary_path,
                            score=score,
                            reason="、".join(reasons),
                            cache_path=target.cache_path,
                            display_filename=display_filename,
                        )
                        result.entries.append(entry)
                    except Exception as exc:
                        result.errors.append(f"{target.group_id}: 截圖審核登記失敗 ({exc})")

            if self.blur_enabled and extension in EXT_PHOTOS:
                is_blurry, score, warning = self.blur_detector.analyze(
                    primary_path,
                    self.blur_threshold,
                )
                if warning and not blur_unavailable_reported:
                    result.warnings.append(warning)
                    blur_unavailable_reported = True
                if is_blurry is True:
                    try:
                        entry = self.workspace.register_review(
                            job_id,
                            target.group_id,
                            "BLURRY",
                            primary_path,
                            score=score,
                            reason=f"Laplacian variance={score:.2f}，門檻={self.blur_threshold:.2f}",
                            cache_path=target.cache_path,
                            display_filename=display_filename,
                        )
                        result.entries.append(entry)
                    except Exception as exc:
                        result.errors.append(f"{target.group_id}: 模糊審核登記失敗 ({exc})")

            if self.short_video_enabled and extension not in EXT_PHOTOS:
                # Live Photo 的短 MOV/MP4 是相片群組的必要成員，分類前直接排除。
                if target.contains_live_photo_video:
                    continue
                duration, warning = self.duration_probe.probe(primary_path)
                if warning:
                    result.warnings.append(f"{target.group_id}: {warning}")
                if duration is not None and 0 < duration <= self.short_video_max_seconds:
                    try:
                        entry = self.workspace.register_review(
                            job_id,
                            target.group_id,
                            "SHORT_VIDEO",
                            primary_path,
                            score=duration,
                            reason=(
                                f"影片長度 {duration:.3f} 秒，"
                                f"門檻 {self.short_video_max_seconds:.3f} 秒"
                            ),
                            cache_path=target.cache_path,
                            display_filename=display_filename,
                        )
                        result.entries.append(entry)
                    except Exception as exc:
                        result.errors.append(
                            f"{target.group_id}: 短影片審核登記失敗 ({exc})"
                        )

        return result
