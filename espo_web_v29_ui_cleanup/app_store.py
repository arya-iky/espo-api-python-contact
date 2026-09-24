import json
import sqlite3
import threading
import time
from pathlib import Path


class AppStore:
    def get_meta(self, key):
        key = str(key).strip()
        with self._lock, self._conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
            row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key, value):
        key = str(key).strip()
        value = "" if value is None else str(value)
        with self._lock, self._conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)", (key, value))
            conn.commit()

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._lock, self._conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS quality_state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                ready INTEGER NOT NULL DEFAULT 0,
                running INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                updated_at REAL,
                error TEXT
            );
            INSERT OR IGNORE INTO quality_state(id, ready, running, total) VALUES(1,0,0,0);
            CREATE TABLE IF NOT EXISTS contact_quality (
                contact_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                score INTEGER NOT NULL,
                display_name TEXT,
                payload TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_quality_status_score ON contact_quality(status, score DESC, updated_at DESC);
            CREATE TABLE IF NOT EXISTS quality_deleted_ids (
                contact_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_records (
                opportunity_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                source_modified_at TEXT,
                accurate_external_id TEXT,
                payload_hash TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_sync_at REAL,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sync_status ON sync_records(status, last_sync_at DESC);
            CREATE TABLE IF NOT EXISTS urgent_done (
                contact_id TEXT PRIMARY KEY,
                completed_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS urgent_index (
                contact_id TEXT PRIMARY KEY,
                display_name TEXT,
                reasons TEXT NOT NULL,
                source_types TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS urgent_state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                ready INTEGER NOT NULL DEFAULT 0,
                running INTEGER NOT NULL DEFAULT 0,
                updated_at REAL,
                error TEXT
            );
            INSERT OR IGNORE INTO urgent_state(id, ready, running) VALUES(1,0,0);
            CREATE TABLE IF NOT EXISTS accurate_tokens (
                id INTEGER PRIMARY KEY CHECK(id=1),
                access_token TEXT,
                refresh_token TEXT,
                expires_at REAL,
                scope TEXT,
                database_id TEXT,
                host TEXT,
                session_id TEXT,
                updated_at REAL
            );
            INSERT OR IGNORE INTO accurate_tokens(id) VALUES(1);
            """)

            stale_urgent = conn.execute("SELECT ready FROM urgent_state WHERE id=1").fetchone()
            urgent_count = conn.execute("SELECT COUNT(*) c FROM urgent_index").fetchone()["c"]
            if stale_urgent and int(stale_urgent["ready"] or 0) == 1 and int(urgent_count or 0) == 0:
                conn.execute("UPDATE urgent_state SET ready=0,running=0,error=NULL,updated_at=0 WHERE id=1")

    def start_quality_scan(self, total):
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE quality_state SET running=1,total=?,error=NULL WHERE id=1", (int(total),))

    def prune_quality(self, keep_ids):
        keep_ids = {str(x) for x in (keep_ids or []) if x}
        with self._lock, self._conn() as conn:
            if not keep_ids:
                return
            ids = [row["contact_id"] for row in conn.execute("SELECT contact_id FROM contact_quality").fetchall()]
            stale = [cid for cid in ids if cid not in keep_ids]
            for start in range(0, len(stale), 500):
                chunk = stale[start:start+500]
                placeholders = ",".join("?" for _ in chunk)
                conn.execute(f"DELETE FROM contact_quality WHERE contact_id IN ({placeholders})", chunk)

    def upsert_quality(self, item):
        contact_id = str(item.get("id") or "").strip()
        if not contact_id:
            return
        payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._conn() as conn:
            tombstone = conn.execute("SELECT 1 FROM quality_deleted_ids WHERE contact_id=?", (contact_id,)).fetchone()
            if tombstone:
                return
            conn.execute("""
                INSERT INTO contact_quality(contact_id,status,score,display_name,payload,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(contact_id) DO UPDATE SET
                    status=excluded.status,
                    score=excluded.score,
                    display_name=excluded.display_name,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
            """, (contact_id, item.get("completenessStatus"), int(item.get("completenessScore") or 0), item.get("displayName"), payload, time.time()))

    def delete_quality(self, contact_id):
        contact_id = str(contact_id).strip()
        if not contact_id:
            return
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM contact_quality WHERE contact_id=?", (contact_id,))
            conn.execute("INSERT OR REPLACE INTO quality_deleted_ids(contact_id, created_at) VALUES(?,?)", (contact_id, time.time()))

    def clear_quality_tombstone(self, contact_id):
        contact_id = str(contact_id).strip()
        if not contact_id:
            return
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM quality_deleted_ids WHERE contact_id=?", (contact_id,))

    def tombstoned_quality_ids(self):
        with self._lock, self._conn() as conn:
            return {row["contact_id"] for row in conn.execute("SELECT contact_id FROM quality_deleted_ids").fetchall()}

    def clear_quality_tombstones(self, ids=None):
        with self._lock, self._conn() as conn:
            if ids is None:
                conn.execute("DELETE FROM quality_deleted_ids")
                return
            ids = [str(x) for x in ids if x]
            if not ids:
                return
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM quality_deleted_ids WHERE contact_id IN ({placeholders})", ids)

    def finish_quality_scan(self, ok, error):
        with self._lock, self._conn() as conn:
            if ok:
                conn.execute("UPDATE quality_state SET ready=1,running=0,updated_at=?,error=NULL WHERE id=1", (time.time(),))
            else:
                conn.execute("UPDATE quality_state SET running=0,error=? WHERE id=1", (error,))

    def invalidate_quality(self, clear_cache=False):
        with self._lock, self._conn() as conn:
            if clear_cache:
                conn.execute("DELETE FROM contact_quality")
                conn.execute("DELETE FROM quality_deleted_ids")
            conn.execute("UPDATE quality_state SET ready=0,updated_at=0,error=NULL WHERE id=1")

    def quality_state(self):
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM quality_state WHERE id=1").fetchone()
            return dict(row) if row else {"ready": False}

    def quality_count(self):
        with self._lock, self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) c FROM contact_quality").fetchone()["c"])

    def quality_counts(self):
        out = {"complete": 0, "partial": 0, "minimal": 0}
        with self._lock, self._conn() as conn:
            for row in conn.execute("SELECT status,COUNT(*) c FROM contact_quality GROUP BY status").fetchall():
                out[row["status"]] = int(row["c"])
        return out

    def quality_page(self, status, page, page_size, search=None):
        where = ["status=?"]
        args = [status]
        if search:
            where.append("(display_name LIKE ? OR payload LIKE ?)")
            needle = f"%{search}%"
            args.extend([needle, needle])
        clause = " AND ".join(where)
        with self._lock, self._conn() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) c FROM contact_quality WHERE {clause}", args).fetchone()["c"])
            offset = max(0, (page - 1) * page_size)
            rows = conn.execute(f"SELECT payload FROM contact_quality WHERE {clause} ORDER BY score DESC,updated_at DESC LIMIT ? OFFSET ?", args + [page_size, offset]).fetchall()
            records = [json.loads(row["payload"]) for row in rows]
        pages = max(1, (total + page_size - 1) // page_size)
        return {"records": records, "total": total, "page": page, "pages": pages, "page_size": page_size, "quality_ready": True}


    def mark_urgent_done(self, contact_id):
        contact_id = str(contact_id).strip()
        if not contact_id:
            return
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO urgent_done(contact_id, completed_at) VALUES(?, ?)",
                (contact_id, time.time()),
            )

    def is_urgent_done(self, contact_id):
        contact_id = str(contact_id).strip()
        if not contact_id:
            return False
        with self._lock, self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM urgent_done WHERE contact_id=?", (contact_id,)
            ).fetchone() is not None

    def urgent_done_ids(self):
        with self._lock, self._conn() as conn:
            return {row["contact_id"] for row in conn.execute("SELECT contact_id FROM urgent_done").fetchall()}

    def urgent_state(self):
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM urgent_state WHERE id=1").fetchone()
            return dict(row) if row else {"ready": 0, "running": 0}

    def urgent_start(self):
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE urgent_state SET running=1,error=NULL WHERE id=1")

    def urgent_finish(self, ok, error=None):
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE urgent_state SET ready=?,running=0,updated_at=?,error=? WHERE id=1", (1 if ok else 0, time.time(), error))

    def urgent_replace_index(self, rows):
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM urgent_index")
            for row in rows:
                conn.execute("INSERT OR REPLACE INTO urgent_index(contact_id,display_name,reasons,source_types,updated_at) VALUES(?,?,?,?,?)", (str(row.get('contactId') or ''), row.get('displayName') or '', json.dumps(row.get('reasons') or [], ensure_ascii=False), json.dumps(row.get('sourceTypes') or [], ensure_ascii=False), time.time()))

    def urgent_index_rows(self, search=None, page=1, page_size=5):
        where=[]; args=[]
        if search:
            where.append("(display_name LIKE ? OR reasons LIKE ?)")
            q=f"%{search}%"; args.extend([q,q])
        clause=(" WHERE " + " AND ".join(where)) if where else ""
        with self._lock, self._conn() as conn:
            total=int(conn.execute(f"SELECT COUNT(*) c FROM urgent_index{clause}", args).fetchone()['c'])
            offset=max(0,(page-1)*page_size)
            rows=conn.execute(f"SELECT * FROM urgent_index{clause} ORDER BY display_name LIMIT ? OFFSET ?", args+[page_size,offset]).fetchall()
        return [dict(r) for r in rows], total

    def sync_get(self, opportunity_id):
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM sync_records WHERE opportunity_id=?", (str(opportunity_id),)).fetchone()
            return dict(row) if row else None

    def sync_save(self, opportunity_id, status, source_modified_at=None, accurate_external_id=None, payload_hash=None, attempts=0, error_message=None):
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT INTO sync_records(opportunity_id,status,source_modified_at,accurate_external_id,payload_hash,attempts,last_sync_at,error_message)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(opportunity_id) DO UPDATE SET
                    status=excluded.status,
                    source_modified_at=excluded.source_modified_at,
                    accurate_external_id=COALESCE(excluded.accurate_external_id,sync_records.accurate_external_id),
                    payload_hash=excluded.payload_hash,
                    attempts=excluded.attempts,
                    last_sync_at=excluded.last_sync_at,
                    error_message=excluded.error_message
            """, (str(opportunity_id), status, source_modified_at, accurate_external_id, payload_hash, int(attempts), time.time(), error_message))

    def record_sync_error(self, opportunity_id, message):
        current = self.sync_get(opportunity_id) or {}
        attempts = int(current.get("attempts") or 0) + 1
        self.sync_save(opportunity_id, "failed", current.get("source_modified_at"), current.get("accurate_external_id"), current.get("payload_hash"), attempts, message)
        return self.sync_get(opportunity_id)

    def list_sync_records(self, limit=100):
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT * FROM sync_records ORDER BY COALESCE(last_sync_at,0) DESC LIMIT ?", (int(limit),)).fetchall()
            return [dict(row) for row in rows]

    def tokens(self):
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM accurate_tokens WHERE id=1").fetchone()
            return dict(row) if row else {}

    def save_tokens(self, **values):
        allowed = {"access_token", "refresh_token", "expires_at", "scope", "database_id", "host", "session_id"}
        fields = {key: values.get(key) for key in allowed if key in values}
        fields["updated_at"] = time.time()
        with self._lock, self._conn() as conn:
            cols = list(fields)
            placeholders = ",".join("?" for _ in cols)
            updates = ",".join(f"{col}=excluded.{col}" for col in cols)
            conn.execute(f"INSERT INTO accurate_tokens(id,{','.join(cols)}) VALUES(1,{placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}", [fields[col] for col in cols])

    def clear_tokens(self):
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE accurate_tokens SET access_token=NULL,refresh_token=NULL,expires_at=NULL,scope=NULL,database_id=NULL,host=NULL,session_id=NULL,updated_at=? WHERE id=1", (time.time(),))
