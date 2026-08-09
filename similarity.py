# -*- coding: utf-8 -*-
"""v3.0 Phase 7－相似照片候選分析。

先以拍攝時間、方向與長寬比縮小候選，再以 64 位元 dHash 的分段索引比對；
不執行全媒體庫 O(n²) 掃描，也不搬移、刪除或修改來源檔案。
"""

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError


DEFAULT_TIME_WINDOW_SECONDS = 15 * 60
DEFAULT_MAX_HAMMING_DISTANCE = 7
DEFAULT_ASPECT_TOLERANCE = 0.06
DEFAULT_DIMENSION_RATIO_MIN = 0.50
DEFAULT_DIMENSION_RATIO_MAX = 2.00
HASH_BAND_COUNT = 8
HASH_BAND_BITS = 8
FILE_HASH_BLOCK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class SimilarityCandidate:
    group_id: str
    path: str
    capture_date: object


@dataclass(frozen=True)
class SimilarityFinding:
    group_id: str
    cluster_id: str
    reference_group_id: str
    hamming_distance: int
    score: float


@dataclass
class SimilarityResult:
    findings: Dict[str, SimilarityFinding] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    candidate_count: int = 0
    comparison_count: int = 0


@dataclass(frozen=True)
class SimilarityFingerprint:
    source: SimilarityCandidate
    timestamp: float
    width: int
    height: int
    aspect_ratio: float
    orientation: str
    aspect_bucket: int
    dhash: int
    file_state: Tuple[int, int]


class SimilarPhotoDetector:
    """以時間分桶與 dHash 分段索引產生相似照片群組。"""

    def __init__(
        self,
        time_window_seconds: int = DEFAULT_TIME_WINDOW_SECONDS,
        max_hamming_distance: int = DEFAULT_MAX_HAMMING_DISTANCE,
        aspect_tolerance: float = DEFAULT_ASPECT_TOLERANCE,
        dimension_ratio_min: float = DEFAULT_DIMENSION_RATIO_MIN,
        dimension_ratio_max: float = DEFAULT_DIMENSION_RATIO_MAX,
    ):
        self.time_window_seconds = max(1, int(time_window_seconds))
        self.max_hamming_distance = max(0, min(64, int(max_hamming_distance)))
        self.aspect_tolerance = max(0.0, float(aspect_tolerance))
        self.dimension_ratio_min = max(0.01, float(dimension_ratio_min))
        self.dimension_ratio_max = max(
            self.dimension_ratio_min,
            float(dimension_ratio_max),
        )

    @staticmethod
    def _timestamp(value: object) -> Optional[float]:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    @staticmethod
    def _dhash(image: Image.Image) -> int:
        sample = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = sample.load()
        result = 0
        for row in range(8):
            for column in range(8):
                result = (result << 1) | int(
                    pixels[column, row] > pixels[column + 1, row]
                )
        return result

    def fingerprint(self, candidate: SimilarityCandidate) -> SimilarityFingerprint:
        """從單一可讀照片建立可持久於記憶體的輕量相似度指紋。"""
        timestamp = self._timestamp(candidate.capture_date)
        if timestamp is None:
            raise ValueError("缺少可解析的拍攝時間")
        before = os.stat(candidate.path)
        state = (before.st_size, before.st_mtime_ns)
        try:
            with Image.open(candidate.path) as opened:
                image = ImageOps.exif_transpose(opened)
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise ValueError("影像尺寸無效")
                dhash = self._dhash(image)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise OSError(f"無法解碼影像 ({exc})") from exc
        after = os.stat(candidate.path)
        if (after.st_size, after.st_mtime_ns) != state:
            raise OSError("媒體在相似度分析期間被外部修改")
        long_edge = max(width, height)
        short_edge = min(width, height)
        aspect_ratio = long_edge / float(short_edge)
        orientation = "S" if width == height else ("L" if width > height else "P")
        aspect_bucket = int(round(aspect_ratio / max(self.aspect_tolerance, 0.01)))
        return SimilarityFingerprint(
            source=candidate,
            timestamp=timestamp,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            orientation=orientation,
            aspect_bucket=aspect_bucket,
            dhash=dhash,
            file_state=state,
        )

    @staticmethod
    def _bands(dhash: int) -> Iterable[Tuple[int, int]]:
        mask = (1 << HASH_BAND_BITS) - 1
        for band_index in range(HASH_BAND_COUNT):
            yield band_index, (dhash >> (band_index * HASH_BAND_BITS)) & mask

    def _dimensions_compatible(
        self,
        first: SimilarityFingerprint,
        second: SimilarityFingerprint,
    ) -> bool:
        if first.orientation != second.orientation:
            return False
        if abs(first.aspect_ratio - second.aspect_ratio) > self.aspect_tolerance:
            return False
        first_area = first.width * first.height
        second_area = second.width * second.height
        ratio = first_area / float(second_area)
        return self.dimension_ratio_min <= ratio <= self.dimension_ratio_max

    @staticmethod
    def _hamming(first: int, second: int) -> int:
        return (first ^ second).bit_count()

    @staticmethod
    def _full_hash(path: str, expected_state: Tuple[int, int]) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                block = handle.read(FILE_HASH_BLOCK_SIZE)
                if not block:
                    break
                hasher.update(block)
        current = os.stat(path)
        if (current.st_size, current.st_mtime_ns) != expected_state:
            raise OSError("媒體在完整雜湊期間被外部修改")
        return hasher.hexdigest()

    def find_similar(
        self,
        candidates: Sequence[SimilarityCandidate],
    ) -> SimilarityResult:
        result = SimilarityResult()
        prepared: List[SimilarityFingerprint] = []
        seen_groups = set()
        for candidate in sorted(candidates, key=lambda item: item.group_id):
            if candidate.group_id in seen_groups:
                continue
            seen_groups.add(candidate.group_id)
            try:
                prepared.append(self.fingerprint(candidate))
            except (OSError, ValueError) as exc:
                result.errors.append(f"{candidate.group_id}: {exc}")
        result.candidate_count = len(prepared)

        parents = {item.source.group_id: item.source.group_id for item in prepared}

        def find(group_id: str) -> str:
            while parents[group_id] != group_id:
                parents[group_id] = parents[parents[group_id]]
                group_id = parents[group_id]
            return group_id

        def union(first_id: str, second_id: str) -> None:
            first_root = find(first_id)
            second_root = find(second_id)
            if first_root == second_root:
                return
            lower, higher = sorted((first_root, second_root))
            parents[higher] = lower

        index: Dict[Tuple[int, str, int, int, int], List[int]] = {}
        compared_pairs = set()
        matched_pairs: List[Tuple[str, str, int]] = []
        full_hash_cache: Dict[str, str] = {}

        for current_index, current in enumerate(prepared):
            time_bucket = int(current.timestamp // self.time_window_seconds)
            candidate_indexes = set()
            for adjacent_time in (time_bucket - 1, time_bucket, time_bucket + 1):
                for adjacent_aspect in (
                    current.aspect_bucket - 1,
                    current.aspect_bucket,
                    current.aspect_bucket + 1,
                ):
                    for band_index, band_value in self._bands(current.dhash):
                        candidate_indexes.update(index.get((
                            adjacent_time,
                            current.orientation,
                            adjacent_aspect,
                            band_index,
                            band_value,
                        ), ()))

            for previous_index in sorted(candidate_indexes):
                pair_key = (previous_index, current_index)
                if pair_key in compared_pairs:
                    continue
                compared_pairs.add(pair_key)
                result.comparison_count += 1
                previous = prepared[previous_index]
                if abs(current.timestamp - previous.timestamp) > self.time_window_seconds:
                    continue
                if not self._dimensions_compatible(previous, current):
                    continue
                distance = self._hamming(previous.dhash, current.dhash)
                if distance > self.max_hamming_distance:
                    continue
                try:
                    for item in (previous, current):
                        group_id = item.source.group_id
                        if group_id not in full_hash_cache:
                            full_hash_cache[group_id] = self._full_hash(
                                item.source.path,
                                item.file_state,
                            )
                except OSError as exc:
                    result.errors.append(f"相似候選完整雜湊失敗: {exc}")
                    continue
                if (
                    full_hash_cache[previous.source.group_id]
                    == full_hash_cache[current.source.group_id]
                ):
                    # 完全重複由 01_重複照片處理，不在 02 重複列出。
                    continue
                union(previous.source.group_id, current.source.group_id)
                matched_pairs.append((
                    previous.source.group_id,
                    current.source.group_id,
                    distance,
                ))

            for band_index, band_value in self._bands(current.dhash):
                index.setdefault((
                    time_bucket,
                    current.orientation,
                    current.aspect_bucket,
                    band_index,
                    band_value,
                ), []).append(current_index)

        clusters: Dict[str, List[str]] = {}
        for group_id in parents:
            clusters.setdefault(find(group_id), []).append(group_id)
        distance_by_group: Dict[str, int] = {}
        for first_id, second_id, distance in matched_pairs:
            distance_by_group[first_id] = min(distance_by_group.get(first_id, 64), distance)
            distance_by_group[second_id] = min(distance_by_group.get(second_id, 64), distance)

        for members in clusters.values():
            if len(members) < 2:
                continue
            ordered = sorted(members)
            reference_id = ordered[0]
            cluster_payload = "\n".join(ordered).encode("utf-8")
            cluster_id = f"sim_{hashlib.sha256(cluster_payload).hexdigest()[:16]}"
            for group_id in ordered:
                distance = distance_by_group.get(group_id, 0)
                result.findings[group_id] = SimilarityFinding(
                    group_id=group_id,
                    cluster_id=cluster_id,
                    reference_group_id=reference_id,
                    hamming_distance=distance,
                    score=round((64 - distance) / 64 * 100, 2),
                )
        return result

    def find_similar_fingerprints(
        self,
        fingerprints: Sequence[SimilarityFingerprint],
        exact_signatures: Optional[Dict[str, object]] = None,
    ) -> SimilarityResult:
        """
        對已完成影像解碼的輕量指紋進行相似分群。

        供 Takeout 串流分析在刪除非命中暫存檔後使用；`exact_signatures`
        用來排除已由 01_重複照片處理的完整內容相同群組。
        """
        prepared = sorted(
            {item.source.group_id: item for item in fingerprints}.values(),
            key=lambda item: item.source.group_id,
        )
        result = SimilarityResult(candidate_count=len(prepared))
        exact_signatures = exact_signatures or {}
        parents = {item.source.group_id: item.source.group_id for item in prepared}

        def find(group_id: str) -> str:
            while parents[group_id] != group_id:
                parents[group_id] = parents[parents[group_id]]
                group_id = parents[group_id]
            return group_id

        def union(first_id: str, second_id: str) -> None:
            first_root = find(first_id)
            second_root = find(second_id)
            if first_root == second_root:
                return
            lower, higher = sorted((first_root, second_root))
            parents[higher] = lower

        index: Dict[Tuple[int, str, int, int, int], List[int]] = {}
        compared_pairs = set()
        matched_pairs: List[Tuple[str, str, int]] = []

        for current_index, current in enumerate(prepared):
            time_bucket = int(current.timestamp // self.time_window_seconds)
            candidate_indexes = set()
            for adjacent_time in (time_bucket - 1, time_bucket, time_bucket + 1):
                for adjacent_aspect in (
                    current.aspect_bucket - 1,
                    current.aspect_bucket,
                    current.aspect_bucket + 1,
                ):
                    for band_index, band_value in self._bands(current.dhash):
                        candidate_indexes.update(index.get((
                            adjacent_time,
                            current.orientation,
                            adjacent_aspect,
                            band_index,
                            band_value,
                        ), ()))

            for previous_index in sorted(candidate_indexes):
                pair_key = (previous_index, current_index)
                if pair_key in compared_pairs:
                    continue
                compared_pairs.add(pair_key)
                result.comparison_count += 1
                previous = prepared[previous_index]
                if abs(current.timestamp - previous.timestamp) > self.time_window_seconds:
                    continue
                if not self._dimensions_compatible(previous, current):
                    continue
                distance = self._hamming(previous.dhash, current.dhash)
                if distance > self.max_hamming_distance:
                    continue
                previous_signature = exact_signatures.get(previous.source.group_id)
                current_signature = exact_signatures.get(current.source.group_id)
                if (
                    previous_signature is not None
                    and current_signature is not None
                    and previous_signature == current_signature
                ):
                    continue
                union(previous.source.group_id, current.source.group_id)
                matched_pairs.append((
                    previous.source.group_id,
                    current.source.group_id,
                    distance,
                ))

            for band_index, band_value in self._bands(current.dhash):
                index.setdefault((
                    time_bucket,
                    current.orientation,
                    current.aspect_bucket,
                    band_index,
                    band_value,
                ), []).append(current_index)

        clusters: Dict[str, List[str]] = {}
        for group_id in parents:
            clusters.setdefault(find(group_id), []).append(group_id)
        distance_by_group: Dict[str, int] = {}
        for first_id, second_id, distance in matched_pairs:
            distance_by_group[first_id] = min(
                distance_by_group.get(first_id, 64),
                distance,
            )
            distance_by_group[second_id] = min(
                distance_by_group.get(second_id, 64),
                distance,
            )
        for members in clusters.values():
            if len(members) < 2:
                continue
            ordered = sorted(members)
            reference_id = ordered[0]
            cluster_id = "sim_" + hashlib.sha256(
                "\n".join(ordered).encode("utf-8")
            ).hexdigest()[:16]
            for group_id in ordered:
                distance = distance_by_group.get(group_id, 0)
                result.findings[group_id] = SimilarityFinding(
                    group_id=group_id,
                    cluster_id=cluster_id,
                    reference_group_id=reference_id,
                    hamming_distance=distance,
                    score=round((64 - distance) / 64 * 100, 2),
                )
        return result
