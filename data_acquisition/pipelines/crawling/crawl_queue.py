import os
import sqlite3
import json
from contextlib import contextmanager


class CrawlQueue:
    """
    Persistent FIFO job queue backed by standard library sqlite3 (`backend/crawl_queue.db`)
    supporting zero-dependency multi-process cross-terminal runtime concurrency.
    Uses BEGIN IMMEDIATE TRANSACTION to guarantee zero duplicate task dequeues.
    """
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
            os.makedirs(base_dir, exist_ok=True)
            db_path = os.path.join(base_dir, "crawl_queue.db")
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    company_id INTEGER,
                    company_name TEXT NOT NULL,
                    target_city TEXT NOT NULL,
                    payload TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    error_message TEXT,
                    jobs_found INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_source_status
                ON crawl_tasks(source_name, status);
            """)
            conn.commit()

    def push_task(self, source_name, company_name, target_city, company_id=None, payload=None):
        payload_str = json.dumps(payload) if isinstance(payload, (dict, list)) else (payload or "")
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO crawl_tasks (source_name, company_id, company_name, target_city, payload, status)
                VALUES (?, ?, ?, ?, ?, 'PENDING')
            """, (str(source_name), company_id, str(company_name), str(target_city), payload_str))
            conn.commit()
            return cursor.lastrowid

    def push_bulk(self, tasks_list):
        """
        Batch enqueue tasks: list of dicts or tuples
        ({source_name, company_name, target_city, company_id, payload})
        """
        rows = []
        for t in tasks_list:
            if isinstance(t, dict):
                p_val = t.get("payload", "")
                p_str = json.dumps(p_val) if isinstance(p_val, (dict, list)) else str(p_val or "")
                rows.append((
                    str(t.get("source_name", "LinkedIn")),
                    t.get("company_id"),
                    str(t.get("company_name", "")),
                    str(t.get("target_city", "")),
                    p_str
                ))
            elif isinstance(t, (tuple, list)) and len(t) >= 3:
                rows.append((
                    str(t[0]),
                    t[1] if len(t) > 3 else None,
                    str(t[1] if len(t) == 3 else t[2]),
                    str(t[2] if len(t) == 3 else t[3]),
                    str(t[4]) if len(t) > 4 else ""
                ))

        with self._get_connection() as conn:
            conn.executemany("""
                INSERT INTO crawl_tasks (source_name, company_id, company_name, target_city, payload, status)
                VALUES (?, ?, ?, ?, ?, 'PENDING')
            """, rows)
            conn.commit()
        return len(rows)

    def pop_task(self, source_name=None):
        """
        Atomically pops the oldest PENDING task for the specified source_name
        (or any source if source_name is None or 'all').
        Returns task dict or None if queue is empty.
        """
        sources = []
        if source_name and str(source_name).strip().lower() != "all":
            sources = [s.strip() for s in str(source_name).split(",") if s.strip()]

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE TRANSACTION")
            if sources:
                placeholders = ",".join(["?"] * len(sources))
                cursor = conn.execute(f"""
                    SELECT * FROM crawl_tasks
                    WHERE source_name IN ({placeholders}) AND status = 'PENDING'
                    ORDER BY created_at ASC, id ASC
                    LIMIT 1
                """, sources)
            else:
                cursor = conn.execute("""
                    SELECT * FROM crawl_tasks
                    WHERE status = 'PENDING'
                    ORDER BY created_at ASC, id ASC
                    LIMIT 1
                """)
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return None

            task_id = row["id"]
            conn.execute("""
                UPDATE crawl_tasks
                SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (task_id,))
            conn.commit()

            task_dict = dict(row)
            task_dict["status"] = "PROCESSING"
            return task_dict
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete_task(self, task_id, jobs_found=0):
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE crawl_tasks
                SET status = 'COMPLETED', jobs_found = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (int(jobs_found), int(task_id)))
            conn.commit()

    def fail_task(self, task_id, error_message):
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE crawl_tasks
                SET status = 'FAILED', error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (str(error_message), int(task_id)))
            conn.commit()

    def get_queue_stats(self):
        stats = {}
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT source_name, status, COUNT(*) as cnt
                FROM crawl_tasks
                GROUP BY source_name, status
            """)
            for row in cursor.fetchall():
                src = row["source_name"]
                st = row["status"]
                cnt = row["cnt"]
                if src not in stats:
                    stats[src] = {"PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "FAILED": 0}
                stats[src][st] = cnt
        return stats

    def clear_completed(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM crawl_tasks WHERE status = 'COMPLETED'")
            conn.commit()
