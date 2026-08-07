# -*- coding: utf-8 -*-
"""
Google Takeout ZIP 匯入引擎 - SQLite 交易狀態與崩潰恢復模組 (v2.2 Phase 2.2 嚴謹邊界與續傳檢索版)
提供符合 ACID 的批次狀態推進、嚴格 commonpath 邊界防禦、歷史 Job 續傳檢索與復原機制。
"""

import os
import sqlite3
import hashlib
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
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"

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
    CURRENT_SCHEMA_VERSION = 3

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()
        self._migrate_db()

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
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (media_member_id) REFERENCES members(member_id),
                FOREIGN KEY (json_member_id) REFERENCES members(member_id)
            );
            """)

            # 常用查詢索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_normalized_path ON members(normalized_path);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_crc_size ON members(member_crc, uncompressed_size);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_filename ON members(filename);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_members_job_status ON members(job_id, status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archives_fingerprint ON archives(fingerprint);")

    def _migrate_db(self):
        """自動 Schema 遷移與舊資料庫外鍵安全的重複資料清理 (FK-Safe Migration)"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # 1. 檢查 archives 欄位
            cursor.execute("PRAGMA table_info(archives);")
            arc_cols = {row['name'] for row in cursor.fetchall()}
            if 'status' not in arc_cols:
                conn.execute("ALTER TABLE archives ADD COLUMN status TEXT NOT NULL DEFAULT 'RUNNING';")
            if 'error_msg' not in arc_cols:
                conn.execute("ALTER TABLE archives ADD COLUMN error_msg TEXT;")

            # 2. 清理重複資料前暫時關閉外鍵檢查，保護外鍵約束不拋出 IntegrityError
            conn.execute("PRAGMA foreign_keys = OFF;")
            try:
                # 重新修正 sidecar_links 外鍵指向最小的 member_id (Canonical Member)
                conn.execute("""
                UPDATE sidecar_links
                SET media_member_id = (
                    SELECT MIN(m.member_id) FROM members m 
                    WHERE m.archive_id = (SELECT archive_id FROM members WHERE member_id = sidecar_links.media_member_id) 
                      AND m.member_index = (SELECT member_index FROM members WHERE member_id = sidecar_links.media_member_id)
                )
                WHERE EXISTS (SELECT 1 FROM members WHERE member_id = sidecar_links.media_member_id);
                """)
                conn.execute("""
                UPDATE sidecar_links
                SET json_member_id = (
                    SELECT MIN(m.member_id) FROM members m 
                    WHERE m.archive_id = (SELECT archive_id FROM members WHERE member_id = sidecar_links.json_member_id) 
                      AND m.member_index = (SELECT member_index FROM members WHERE member_id = sidecar_links.json_member_id)
                )
                WHERE EXISTS (SELECT 1 FROM members WHERE member_id = sidecar_links.json_member_id);
                """)

                # 清理重複的 sidecar_links
                conn.execute("""
                DELETE FROM sidecar_links WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM sidecar_links GROUP BY job_id, json_member_id
                );
                """)
                # 清理重複的 members
                conn.execute("""
                DELETE FROM members WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM members GROUP BY archive_id, member_index
                );
                """)
            finally:
                conn.execute("PRAGMA foreign_keys = ON;")

            # 3. 建立唯一索引以支援 ON CONFLICT (archive_id, member_index) 語法
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_members_archive_member ON members(archive_id, member_index);")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sidecar_unique ON sidecar_links(job_id, json_member_id);")

            # 4. 外鍵完整性檢查
            conn.execute("PRAGMA foreign_key_check;")

            # 5. 更新 user_version
            conn.execute(f"PRAGMA user_version = {self.CURRENT_SCHEMA_VERSION};")

    def create_job(self, job_id: str, job_type: str, src_dir: str, dst_dir: str) -> str:
        now = datetime.datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, job_type, src_dir, dst_dir, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, job_type, src_dir, dst_dir, now, now, "RUNNING")
            )
        return job_id

    def find_resumable_job(self, src_dir: str, dst_dir: str, archive_fingerprints: List[str]) -> Optional[str]:
        """
        尋找可續傳的歷史 Job（相同 src, dst 且封存檔指紋完全吻合，狀態非終止）
        """
        if not archive_fingerprints:
            return None

        norm_src = os.path.abspath(src_dir)
        norm_dst = os.path.abspath(dst_dir)

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT job_id FROM jobs 
                WHERE src_dir = ? AND dst_dir = ? AND status IN (?, ?, ?)
                ORDER BY created_at DESC
                """,
                (norm_src, norm_dst, "RUNNING", TakeoutState.FAILED, TakeoutState.COMPLETED_WITH_ERRORS)
            )
            jobs = cursor.fetchall()

            for j in jobs:
                jid = j['job_id']
                cursor.execute("SELECT fingerprint FROM archives WHERE job_id = ?", (jid,))
                db_fps = {r['fingerprint'] for r in cursor.fetchall()}
                if db_fps and db_fps == set(archive_fingerprints):
                    return jid

        return None

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

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
            # 若已有相同 job_id 與 fingerprint，直接回傳 archive_id
            cursor.execute("SELECT archive_id FROM archives WHERE job_id = ? AND fingerprint = ?", (job_id, fingerprint))
            row = cursor.fetchone()
            if row:
                return row['archive_id']

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

    def get_archive(self, archive_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM archives WHERE archive_id = ?", (archive_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def register_members_batch(self, members_data: List[Dict[str, Any]]):
        """採用安全 UPSERT (ON CONFLICT DO UPDATE) 替代 INSERT OR REPLACE，保護 member_id 不變"""
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
            INSERT INTO members (
                job_id, archive_id, archive_fingerprint, member_index, member_name,
                normalized_path, filename, member_crc, uncompressed_size, compressed_size,
                is_media, is_json, status, error_msg, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(archive_id, member_index) DO UPDATE SET
                status = excluded.status,
                error_msg = excluded.error_msg,
                updated_at = excluded.updated_at
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
        self.update_members_status_batch([member_id], status, **kwargs)

    def update_members_status_batch(self, member_ids: List[int], status: str, **kwargs):
        """高效能單一交易批次更新狀態"""
        if not member_ids:
            return
        now = datetime.datetime.now().isoformat()
        fields = ["status = ?", "updated_at = ?"]
        params = [status, now]

        for key, val in kwargs.items():
            if key in ('part_path', 'sha256', 'date_candidate', 'date_source', 'date_confidence', 'dest_reserved', 'final_destination', 'error_msg'):
                fields.append(f"{key} = ?")
                params.append(val)

        sql = f"UPDATE members SET {', '.join(fields)} WHERE member_id = ?"
        rows = [tuple(params + [mid]) for mid in member_ids]

        with self._get_conn() as conn:
            conn.executemany(sql, rows)

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

    def _is_safe_part_path(self, job_id: str, part_path: str) -> bool:
        """
        嚴格邊界檢查 (使用 os.path.commonpath)
        part_path 必須位於特定 job 的暫存目錄 `<dst>\_ImportTemp\<job_id>\` 內部，
        副檔名必須為 .part，且非符號連結。
        """
        if not part_path or os.path.islink(part_path):
            return False

        job_info = self.get_job(job_id)
        if not job_info:
            return False

        dst_dir = os.path.realpath(job_info['dst_dir'])
        job_temp_dir = os.path.realpath(os.path.join(dst_dir, "_ImportTemp", job_id))
        real_part = os.path.realpath(part_path)

        # 1. 檢查副檔名
        if not real_part.lower().endswith('.part'):
            return False

        # 2. 精準檢查 commonpath 是否屬於工作專屬暫存目錄
        try:
            common = os.path.commonpath([job_temp_dir, real_part])
            return os.path.normcase(common) == os.path.normcase(job_temp_dir)
        except ValueError:
            return False

    def _compute_sha256(self, filepath: str) -> str:
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(64 * 1024):
                h.update(chunk)
        return h.hexdigest()

    def recover_and_get_pending_members(self, job_id: str) -> List[Dict[str, Any]]:
        """
        Phase 2 崩潰恢復與續傳引擎 (Crash Recovery Engine - 帶 commonpath 邊界防禦)
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM members WHERE job_id = ? AND is_media = 1 AND status NOT IN (?, ?, ?, ?, ?)",
                (
                    job_id,
                    TakeoutState.COMPLETED,
                    TakeoutState.SECURITY_REJECTED,
                    TakeoutState.DUPLICATE_SKIPPED,
                    TakeoutState.RECOVERY_CONFLICT,
                    TakeoutState.CANCELLED
                )
            )
            rows = [dict(r) for r in cursor.fetchall()]

        pending_members = []

        for m in rows:
            mid = m['member_id']
            status = m['status']
            part_p = m['part_path']
            dest_p = m['dest_reserved'] or m['final_destination']

            is_part_safe = part_p is not None and self._is_safe_part_path(job_id, part_p)
            part_exists = is_part_safe and os.path.isfile(part_p)
            dest_exists = dest_p is not None and os.path.isfile(dest_p) and not os.path.islink(dest_p)

            # 1. EXTRACTING 狀態處置
            if status == TakeoutState.EXTRACTING:
                if part_exists:
                    try: os.remove(part_p)
                    except OSError: pass
                self.update_member_status(mid, TakeoutState.SECURITY_VALIDATED, part_path=None, sha256=None)
                m['status'] = TakeoutState.SECURITY_VALIDATED
                m['part_path'] = None
                pending_members.append(m)

            # 2. VERIFIED / METADATA_PARSED 狀態處置
            elif status in (TakeoutState.VERIFIED, TakeoutState.METADATA_PARSED):
                if part_exists:
                    pending_members.append(m)
                else:
                    self.update_member_status(mid, TakeoutState.SECURITY_VALIDATED, part_path=None, sha256=None)
                    m['status'] = TakeoutState.SECURITY_VALIDATED
                    m['part_path'] = None
                    pending_members.append(m)

            # 3. DESTINATION_RESERVED 狀態處置
            elif status == TakeoutState.DESTINATION_RESERVED:
                if part_exists and not dest_exists:
                    pending_members.append(m)
                elif not part_exists and dest_exists:
                    try:
                        st = os.stat(dest_p)
                        if st.st_size == m['uncompressed_size']:
                            if m['sha256'] and self._compute_sha256(dest_p) == m['sha256']:
                                self.update_member_status(mid, TakeoutState.COMPLETED, final_destination=dest_p)
                                continue
                    except OSError:
                        pass
                    self.update_member_status(mid, TakeoutState.RECOVERY_CONFLICT, error_msg="目的檔存在但 SHA-256 校驗不符")
                elif part_exists and dest_exists:
                    self.update_member_status(mid, TakeoutState.RECOVERY_CONFLICT, error_msg="Part 與 Dest 同時存在，禁止覆寫")
                else:
                    self.update_member_status(mid, TakeoutState.SECURITY_VALIDATED, part_path=None)
                    m['status'] = TakeoutState.SECURITY_VALIDATED
                    pending_members.append(m)

            else:
                pending_members.append(m)

        return pending_members
