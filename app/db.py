"""SQLite: загруженные файлы и задачи (история). WAL — чтобы бот и воркер писали одновременно."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    file_id    TEXT NOT NULL,
    file_name  TEXT NOT NULL,
    ext        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    size       INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    chat_id        INTEGER NOT NULL,
    op             TEXT NOT NULL,
    params         TEXT NOT NULL DEFAULT '{}',
    upload_ids     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    status_msg_id  INTEGER,
    error          TEXT,
    input_name     TEXT,
    input_size     INTEGER,
    result_name    TEXT,
    result_size    INTEGER,
    result_file_ids TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    started_at     TEXT,
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS jobs_user ON jobs(user_id, id DESC);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, id);
"""


@dataclass
class Upload:
    id: int
    user_id: int
    file_id: str
    file_name: str
    ext: str
    kind: str
    size: int | None


@dataclass
class Job:
    id: int
    user_id: int
    chat_id: int
    op: str
    params: dict
    upload_ids: list[int]
    status: str
    status_msg_id: int | None
    error: str | None
    input_name: str | None
    input_size: int | None
    result_name: str | None
    result_size: int | None
    result_file_ids: list[str]
    created_at: str
    started_at: str | None
    finished_at: str | None


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)


# ---------- uploads ----------
def add_upload(user_id: int, file_id: str, file_name: str, ext: str, kind: str, size: int | None) -> int:
    with connect() as c:
        return c.execute(
            "INSERT INTO uploads(user_id, file_id, file_name, ext, kind, size) VALUES (?,?,?,?,?,?)",
            (user_id, file_id, file_name, ext, kind, size),
        ).lastrowid


def get_upload(upload_id: int) -> Upload | None:
    with connect() as c:
        r = c.execute("SELECT id, user_id, file_id, file_name, ext, kind, size FROM uploads WHERE id=?",
                      (upload_id,)).fetchone()
    return Upload(*r) if r else None


def get_uploads(ids: list[int]) -> list[Upload]:
    found = {u.id: u for u in (get_upload(i) for i in ids) if u}
    return [found[i] for i in ids if i in found]


# ---------- jobs ----------
def _job(r: sqlite3.Row) -> Job:
    d = dict(r)
    d["params"] = json.loads(d["params"] or "{}")
    d["upload_ids"] = json.loads(d["upload_ids"])
    d["result_file_ids"] = json.loads(d["result_file_ids"] or "[]")
    return Job(**d)


def create_job(user_id: int, chat_id: int, op: str, params: dict, uploads: list[Upload]) -> int:
    with connect() as c:
        return c.execute(
            "INSERT INTO jobs(user_id, chat_id, op, params, upload_ids, input_name, input_size) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, chat_id, op, json.dumps(params), json.dumps([u.id for u in uploads]),
             uploads[0].file_name if len(uploads) == 1 else f"{len(uploads)} файлов",
             sum(u.size or 0 for u in uploads)),
        ).lastrowid


def get_job(job_id: int) -> Job | None:
    with connect() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _job(r) if r else None


def set_status_msg(job_id: int, msg_id: int) -> None:
    with connect() as c:
        c.execute("UPDATE jobs SET status_msg_id=? WHERE id=?", (msg_id, job_id))


def mark_running(job_id: int) -> None:
    with connect() as c:
        c.execute("UPDATE jobs SET status='running', started_at=datetime('now') WHERE id=?", (job_id,))


def mark_done(job_id: int, result_name: str, result_size: int, file_ids: list[str]) -> None:
    with connect() as c:
        c.execute(
            "UPDATE jobs SET status='done', result_name=?, result_size=?, result_file_ids=?, "
            "finished_at=datetime('now') WHERE id=?",
            (result_name, result_size, json.dumps(file_ids), job_id),
        )


def mark_error(job_id: int, error: str) -> None:
    with connect() as c:
        c.execute("UPDATE jobs SET status='error', error=?, finished_at=datetime('now') WHERE id=?",
                  (error[:500], job_id))


def queue_position(job_id: int) -> int:
    """Сколько задач стоит в очереди перед этой (включая её)."""
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM jobs WHERE status='queued' AND id<=?", (job_id,)).fetchone()[0]


def active_jobs(user_id: int) -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')",
                         (user_id,)).fetchone()[0]


def history(user_id: int, limit: int = 15) -> list[Job]:
    with connect() as c:
        rows = c.execute("SELECT * FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    return [_job(r) for r in rows]


def reset_stuck_jobs() -> list[Job]:
    """После перезапуска воркера задачи в статусе running уже никто не выполняет."""
    with connect() as c:
        rows = c.execute("SELECT * FROM jobs WHERE status='running'").fetchall()
        c.execute("UPDATE jobs SET status='error', error='Сервер перезапустился во время обработки', "
                  "finished_at=datetime('now') WHERE status='running'")
    return [_job(r) for r in rows]


def stats() -> dict:
    with connect() as c:
        row = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id), SUM(status='done'), SUM(status='error'), "
            "SUM(status IN ('queued','running')) FROM jobs"
        ).fetchone()
    return dict(zip(("jobs", "users", "done", "errors", "active"), (v or 0 for v in row)))
