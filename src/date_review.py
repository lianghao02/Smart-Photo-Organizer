# -*- coding: utf-8 -*-
"""v3.0 Phase 8－MediaGroup 日期異常人工審核與稽核報表。"""

import csv
import os
import uuid
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from review_workspace import ReviewEntry, ReviewWorkspaceManager


DEFAULT_LOW_CONFIDENCE_THRESHOLD = 50
DATE_AUDIT_FILENAME = "date_audit.csv"


@dataclass(frozen=True)
class DateReviewTarget:
    group_id: str
    target_path: str
    display_filename: str
    capture_date: Optional[str]
    date_source: Optional[str]
    confidence: Optional[int]
    conflict: bool = False
    cache_path: Optional[str] = None
    candidate_summary: Optional[str] = None

    @classmethod
    def from_analysis_target(cls, target) -> "DateReviewTarget":
        return cls(
            group_id=target.group_id,
            target_path=target.primary_path,
            display_filename=(
                target.original_filename or os.path.basename(target.primary_path)
            ),
            capture_date=target.capture_date,
            date_source=target.date_source,
            confidence=target.date_confidence,
            conflict=bool(target.date_conflict),
            cache_path=target.cache_path,
        )


@dataclass
class DateReviewResult:
    entries: List[ReviewEntry] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    audit_path: Optional[str] = None
    reviewed_count: int = 0


class DateAnomalyReviewer:
    """將衝突、日期缺失或低可信度群組登記至 06_日期異常。"""

    AUDIT_HEADERS = (
        "MediaGroup ID",
        "檔名",
        "拍攝日期",
        "日期來源",
        "可信度",
        "日期衝突",
        "判定",
        "候選摘要",
    )

    def __init__(
        self,
        workspace: ReviewWorkspaceManager,
        low_confidence_threshold: int = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    ):
        self.workspace = workspace
        self.low_confidence_threshold = max(0, min(100, int(low_confidence_threshold)))

    def issue_for(self, target: DateReviewTarget) -> Optional[str]:
        """回傳需人工審核的日期原因；`None` 代表日期可供後續歸檔。"""
        if target.conflict:
            return "高可信度日期來源互相衝突"
        if not target.capture_date:
            return "找不到可靠拍攝日期"
        if target.confidence is None:
            return "日期可信度未知"
        if int(target.confidence) < self.low_confidence_threshold:
            return (
                f"日期可信度 {int(target.confidence)} 分，"
                f"低於 {self.low_confidence_threshold} 分門檻"
            )
        return None

    @staticmethod
    def _csv_safe(value: object) -> str:
        text = "" if value is None else str(value)
        if text.startswith(("=", "+", "-", "@")):
            return "'" + text
        return text

    def _write_audit(self, rows: List[List[object]]) -> Optional[str]:
        if self.workspace.dry_run:
            return None
        self.workspace.initialize()
        report_path = os.path.join(self.workspace.review_root, DATE_AUDIT_FILENAME)
        part_path = f"{report_path}.{uuid.uuid4().hex}.part"
        try:
            with open(part_path, "x", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(self.AUDIT_HEADERS)
                for row in rows:
                    writer.writerow([self._csv_safe(value) for value in row])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(part_path, report_path)
            return report_path
        finally:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass

    def review(
        self,
        job_id: str,
        targets: Iterable[DateReviewTarget],
    ) -> DateReviewResult:
        result = DateReviewResult()
        unique = {}
        for target in targets:
            unique.setdefault(target.group_id, target)
        audit_rows: List[List[object]] = []

        for group_id in sorted(unique):
            target = unique[group_id]
            issue = self.issue_for(target)
            result.reviewed_count += 1
            audit_rows.append([
                target.group_id,
                target.display_filename,
                target.capture_date,
                target.date_source,
                target.confidence,
                "是" if target.conflict else "否",
                issue or "正常",
                target.candidate_summary,
            ])
            if issue is None:
                continue
            reason_parts = [issue]
            if target.date_source:
                reason_parts.append(f"目前來源：{target.date_source}")
            if target.capture_date:
                reason_parts.append(f"目前日期：{target.capture_date}")
            if target.candidate_summary:
                reason_parts.append(f"候選：{target.candidate_summary}")
            try:
                entry = self.workspace.register_review(
                    job_id,
                    target.group_id,
                    "DATE_ANOMALY",
                    target.target_path,
                    score=target.confidence,
                    reason="；".join(reason_parts),
                    cache_path=target.cache_path,
                    display_filename=target.display_filename,
                )
                result.entries.append(entry)
            except Exception as exc:
                result.errors.append(f"{target.group_id}: 日期異常審核登記失敗 ({exc})")

        try:
            result.audit_path = self._write_audit(audit_rows)
        except OSError as exc:
            result.errors.append(f"日期稽核報表寫入失敗 ({exc})")
        return result
