# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - SQLite 交易狀態與崩潰恢復模組 (v1.1 高效能批次與約束版)
管理 takeout_import.db 資料庫，提供符合 ACID 的批次狀態推進與復原機制。
"""

import os
import sqlite3
import datetime
from typing import Optional, Dict, Any, List


class TakeoutState:
    # 推進狀態
    DISCOVERED = "DISCOVERED"
    SECURITY_VALIDATED = "SECURITY_VALIDATED"
    INDEXED = "INDEXED"
    EXTRACTING = "EXTRACTING"
    VERIFIED = "VERIFIED"
    METADATA_PARSED = "METADATA_PARSED"
    DESTINATION_RESERVED = "DESTINATION_RESERVED"
    COMPLETED = "COMPLETED"

    # 預覽狀態
    PREVIEW_ANALYZED = "PREVIEW_ANALYZED"

    # 終止與異常狀態
    FAILED = "FAILED"
    SECURITY_REJECTED = "SECURITY_REJECTED"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RECOVERY_CONFLICT = "RECOVERY_CONFLICT"
    CANCELLED = "CANCELLED"


class JobType:
    IMPORT = "IMPORT"
    PREVIEW = "PREVIEW"


class TakeoutStateManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            # 任務主表
            conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                src_dir TEXT NOT NULL,
                dst_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL
            );
            """)

            # 封存檔紀錄表
            conn.execute("""
            CREATE TABLE IF NOT EXISTS archives (
                archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                archive_path TEXT NOT NULL,
                archive_size INTEGER NOT NULL,
                archive_mtime REAL NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                error_msg TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id)
            );
            """)

            # ZIP 成員狀態表
            conn.execute("""
            CREATE TABLE IF NOT EXISTS members (
                member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                archive_id INTEGER NOT NULL,
                archive_fingerprint TEXT NOT NULL,
                member_index INTEGER NOT NULL,
                member_name TEXT NOT NULL,
                normalized_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                member_crc INTEGER NOT NULL,
                uncompressed_size INTEGER NOT NULL,
                compressed_size INTEGER NOT NULL,
                is_media INTEGER NOT NULL,
                is_json INTEGER NOT NULL,
                status TEXT NOT NULL,
                part_path TEXT,
                sha256 TEXT,
                date_candidate TEXT,
                date_source TEXT,
                date_confidence INTEGER,
                dest_reserved TEXT,
                final_destination TEXT,
                error_msg TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(archive_id, member_index),
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (archive_id) REFERENCES archives(archive_id)
            );
            """)

            # Sidecar 配對表
            conn.execute("""
            CREATE TABLE IF NOT EXISTS sidecar_links (
                link_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                media_member_id INTEGER NOT NULL,
                json_member_id INTEGER NOT NULL,
                match_quality TEXT NOT NULL,
                UNIQUE(job_id, media_member_id, json_member_id),
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (media_member_id) REFERENCES members(member_id),
                FOREIGN KEY (json_member_id) REFERENCES members(member_id)
            );
            """)

            # 索引建立
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_normalized_path ON members(normalized_path);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_crc_size ON members(member_crc, uncompressed_size);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_filename ON members(filename);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_job_status ON members(job_id, status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archives_fingerprint ON archives(fingerprint);")

    def create_job(self, job_id: str, job_type: str, src_dir: str, dst_dir: str) -> str:
        now = datetime.datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, job_type, src_dir, dst_dir, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, job_type, src_dir, dst_dir, now, now, "RUNNING")
            )
        return job_id

    def update_job_status(self, job_id: str, status: str):
        now = datetime.datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (status, now, job_id)
            )

    def record_archive(self, job_id: str, archive_path: str, archive_size: int, archive_mtime: float, fingerprint: str) -> int:
        now = datetime.datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO archives (job_id, archive_path, archive_size, archive_mtime, fingerprint, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, archive_path, archive_size, archive_mtime, fingerprint, "RUNNING", now)
            )
            return cursor.lastrowid

    def update_archive_status(self, archive_id: int, status: str, error_msg: Optional[str] = None):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE archives SET status = ?, error_msg = ? WHERE archive_id = ?",
                (status, error_msg, archive_id)
            )

    def register_members_batch(self, members_data: List[Dict[str, Any]]):
        """高效能批次插入成員，單一交易 Commit 避免硬碟頻繁 IO"""
        if not members_data:
            return
        now = datetime.datetime.now().isoformat()
        rows = [
            (
                m['job_id'],
                m['archive_id'],
                m['archive_fingerprint'],
                m['member_index'],
                m['member_name'],
                m['normalized_path'],
                m['filename'],
                m['member_crc'],
                m['uncompressed_size'],
                m['compressed_size'],
                1 if m.get('is_media') else 0,
                1 if m.get('is_json') else 0,
                m.get('status', TakeoutState.DISCOVERED),
                m.get('reject_reason'),
                now
            )
            for m in members_data
        ]
        with self._get_conn() as conn:
            conn.executemany("""
            INSERT OR REPLACE INTO members (
                job_id, archive_id, archive_fingerprint, member_index, member_name,
                normalized_path, filename, member_crc, uncompressed_size, compressed_size,
                is_media, is_json, status, error_msg, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

    def register_member(self, member_data: Dict[str, Any]) -> int:
        self.register_members_batch([member_data])
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT member_id FROM members WHERE archive_id = ? AND member_index = ?",
                (member_data['archive_id'], member_data['member_index'])
            )
            row = cursor.fetchone()
            return row['member_id'] if row else 0

    def update_member_status(self, member_id: int, status: str, **kwargs):
        now = datetime.datetime.now().isoformat()
        fields = ["status = ?", "updated_at = ?"]
        params = [status, now]

        for key, val in kwargs.items():
            if key in ('part_path', 'sha256', 'date_candidate', 'date_source', 'date_confidence', 'dest_reserved', 'final_destination', 'error_msg'):
                fields.append(f"{key} = ?")
                params.append(val)

        params.append(member_id)
        sql = f"UPDATE members SET {', '.join(fields)} WHERE member_id = ?"

        with self._get_conn() as conn:
            conn.execute(sql, params)

    def get_member(self, member_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM members WHERE member_id = ?", (member_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_job_members_by_status(self, job_id: str, status: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM members WHERE job_id = ? AND status = ?", (job_id, status))
            return [dict(row) for row in cursor.fetchall()]
