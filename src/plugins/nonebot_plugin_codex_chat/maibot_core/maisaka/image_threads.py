"""Durable independent image thread IDs and message associations."""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from pathlib import Path

_DB = Path("/app/data/nonebot_chat_agent/generated_images/image_threads.sqlite3")
TERMINAL = frozenset({"sent", "failed", "send_failed", "cancelled", "timed_out"})
STATES = TERMINAL | {"planning", "searching", "awaiting_clarification", "queued", "generating", "sending", "delivery_uncertain"}

def _connect():
    _DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(_DB), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY, session TEXT NOT NULL, owner TEXT NOT NULL,
        root TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL,
        deadline REAL, job_id TEXT, created REAL NOT NULL,
        UNIQUE(session, root))""")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS image_thread_job_unique ON threads(job_id) WHERE job_id IS NOT NULL")
    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        session TEXT NOT NULL, msg_id TEXT NOT NULL, thread_id TEXT NOT NULL,
        role TEXT NOT NULL, PRIMARY KEY(session, msg_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS timeout_notices (
        thread_id TEXT PRIMARY KEY, session TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', claimed_at REAL,
        sent_at REAL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS thread_context (
        thread_id TEXT PRIMARY KEY, request TEXT NOT NULL DEFAULT '',
        question TEXT NOT NULL DEFAULT '', supplements TEXT NOT NULL DEFAULT '[]')""")
    return db

def _dict(row):
    return dict(row) if row is not None else None

def get_thread(thread_id):
    with _connect() as db:
        return _dict(db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone())

def thread_for_message(session, msg_id):
    with _connect() as db:
        return _dict(db.execute("""SELECT t.* FROM threads t JOIN messages m ON m.thread_id=t.id
            WHERE m.session=? AND m.msg_id=?""", (session, msg_id)).fetchone())

def quoted_clarification_thread(session, owner, quote_id):
    """Only a bot clarification message may route a user continuation."""
    with _connect() as db:
        return _dict(db.execute("""SELECT t.* FROM threads t
            JOIN messages m ON m.thread_id=t.id
            WHERE m.session=? AND m.msg_id=? AND m.role='bot'
              AND t.owner=? AND t.status='awaiting_clarification'
              AND t.deadline>?""",
            (session, quote_id, owner, time.time())).fetchone())

def thread_context(thread_id):
    with _connect() as db:
        row = db.execute("SELECT * FROM thread_context WHERE thread_id=?", (thread_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["supplements"] = json.loads(data["supplements"])
        return data


def record_question(thread_id, session, owner, msg_ids, request, question, *, now=None):
    """Atomically index delivered bot questions and refresh only this live thread."""
    now = time.time() if now is None else float(now)
    ids = [str(mid) for mid in msg_ids if str(mid)]
    if not ids:
        return None
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        t = db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
        if (not t or t["session"] != session or t["owner"] != owner
                or t["status"] in TERMINAL or t["job_id"]
                or (t["status"] == "awaiting_clarification" and t["deadline"] <= now)):
            return None
        for mid in ids:
            old = db.execute("SELECT thread_id,role FROM messages WHERE session=? AND msg_id=?",
                             (session, mid)).fetchone()
            if old and (old["thread_id"] != thread_id or old["role"] != "bot"):
                raise ValueError("Question already belongs to another thread")
            db.execute("INSERT OR IGNORE INTO messages VALUES (?,?,?,'bot')", (session, mid, thread_id))
        db.execute("""INSERT INTO thread_context(thread_id,request,question) VALUES (?,?,?)
            ON CONFLICT(thread_id) DO UPDATE SET
            request=CASE WHEN request='' THEN excluded.request ELSE request END,
            question=excluded.question""", (thread_id, request, question))
        db.execute("""UPDATE threads SET status='awaiting_clarification', deadline=?,
            version=version+1 WHERE id=?""", (now + 300, thread_id))
        return _dict(db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone())


def accept_quoted_reply(session, owner, quote_ids, msg_id, text, *, now=None):
    """Receipt and timeout compete under one SQLite write lock."""
    now = time.time() if now is None else float(now)
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        matches = db.execute("""SELECT DISTINCT t.* FROM threads t
            JOIN messages m ON m.thread_id=t.id WHERE m.session=? AND m.role='bot'
            AND m.msg_id IN (SELECT value FROM json_each(?)) AND t.owner=?
            AND t.status='awaiting_clarification' AND t.deadline>?""",
            (session, json.dumps(list(quote_ids)), owner, now)).fetchall()
        if len(matches) != 1:
            return None
        t = matches[0]
        old = db.execute("SELECT thread_id FROM messages WHERE session=? AND msg_id=?",
                         (session, msg_id)).fetchone()
        if old:
            return _dict(t) if old["thread_id"] == t["id"] else None
        db.execute("INSERT INTO messages VALUES (?,?,?,'user')", (session, msg_id, t["id"]))
        context = db.execute("SELECT supplements FROM thread_context WHERE thread_id=?", (t["id"],)).fetchone()
        if context:
            supplements = json.loads(context["supplements"])
            supplements.append(text[:2000])
            db.execute("UPDATE thread_context SET supplements=? WHERE thread_id=?",
                       (json.dumps(supplements, ensure_ascii=False), t["id"]))
        db.execute("UPDATE threads SET deadline=?, version=version+1 WHERE id=?", (now + 300, t["id"]))
        return _dict(db.execute("SELECT * FROM threads WHERE id=?", (t["id"],)).fetchone())


def reply_target_ids(message):
    return [str(getattr(part, "target_message_id", "") or "").strip()
            for part in (getattr(getattr(message, "raw_message", None), "components", ()) or ())
            if type(part).__name__ == "ReplyComponent" and getattr(part, "target_message_id", None)]

def create_thread(session, owner, root):
    """Same root is idempotent; independent roots do not replace each other."""
    if not all((session, owner, root)):
        raise ValueError("Missing thread identity")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM threads WHERE session=? AND root=?", (session, root)).fetchone()
        if old:
            if old["owner"] != owner:
                raise ValueError("Root owner mismatch")
            return _dict(old)
        if db.execute("SELECT 1 FROM messages WHERE session=? AND msg_id=?", (session, root)).fetchone():
            raise ValueError("Message already assigned")
        tid = uuid.uuid4().hex
        db.execute("INSERT INTO threads VALUES (?,?,?,?, 'planning',0,NULL,NULL,?)",
                   (tid, session, owner, root, time.time()))
        db.execute("INSERT INTO messages VALUES (?,?,?,'user')", (session, root, tid))
        return _dict(db.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone())

def attach_message(thread_id, session, owner, msg_id, role):
    """Bind actual bot question IDs and user followups without reassigning messages."""
    if role not in {"bot", "user"} or not msg_id:
        raise ValueError("Invalid message")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        t = db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
        if not t or t["session"] != session or t["owner"] != owner or t["status"] in TERMINAL:
            raise ValueError("Thread unavailable or ownership mismatch")
        old = db.execute("SELECT thread_id,role FROM messages WHERE session=? AND msg_id=?",
                         (session, msg_id)).fetchone()
        if old:
            if old["thread_id"] != thread_id or old["role"] != role:
                raise ValueError("Message belongs to another thread")
            return False
        db.execute("INSERT INTO messages VALUES (?,?,?,?)", (session, msg_id, thread_id, role))
        return True

def job_can_run(job_id, *, sending=False):
    """A bound job may run only while its own thread is live."""
    thread = thread_for_job(job_id)
    if thread is None:
        return False
    if thread["status"] in TERMINAL or thread["status"] == "delivery_uncertain":
        return False
    return thread["status"] in ({"generating", "sending"} if sending else
                               {"queued", "generating"})


def thread_for_job(job_id):
    with _connect() as db:
        return _dict(db.execute("SELECT * FROM threads WHERE job_id=?", (job_id,)).fetchone())


def advance_job(job_id, status):
    """Update only the thread owning this job; never a user's latest thread."""
    thread = thread_for_job(job_id)
    if thread is None or thread["status"] in TERMINAL:
        return None
    return transition(thread["id"], thread["version"], status)


def bind_job(thread_id, job_id):
    thread = get_thread(thread_id)
    if (not thread or thread["status"] in TERMINAL or thread["job_id"]
            or (thread["status"] == "awaiting_clarification" and thread["deadline"] <= time.time())):
        return None
    if thread["status"] not in {"planning", "searching", "awaiting_clarification"}:
        return None
    return transition(thread_id, thread["version"], "queued", job_id=job_id)


def expire_due_threads(now=None):
    """Atomically claim overdue clarifications, including after a restart."""
    now = time.time() if now is None else float(now)
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("""SELECT * FROM threads
            WHERE status='awaiting_clarification' AND deadline<=?""", (now,)).fetchall()
        for row in rows:
            db.execute("""UPDATE threads SET status='timed_out', version=version+1,
                deadline=NULL WHERE id=? AND version=? AND status='awaiting_clarification'
                AND deadline<=?""", (row["id"], row["version"], now))
            db.execute("INSERT OR IGNORE INTO timeout_notices(thread_id,session) VALUES (?,?)",
                       (row["id"], row["session"]))
        return [dict(row) for row in rows]

def claim_timeout_notice(session):
    """Claim once before external transport; interrupted sends remain uncertain."""
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT n.thread_id, t.owner, t.root FROM timeout_notices n
            JOIN threads t ON t.id=n.thread_id
            WHERE n.session=? AND n.status='pending'
            ORDER BY t.created LIMIT 1""", (session,)).fetchone()
        if row is None:
            return None
        db.execute("""UPDATE timeout_notices SET status='sending', claimed_at=?
            WHERE thread_id=? AND status='pending'""", (time.time(), row["thread_id"]))
        return dict(row)


def complete_timeout_notice(thread_id, sent):
    with _connect() as db:
        db.execute("""UPDATE timeout_notices SET status=?, sent_at=?
            WHERE thread_id=? AND status='sending'""",
            ("sent" if sent else "uncertain", time.time() if sent else None, thread_id))


def timeout_notice_status(thread_id):
    with _connect() as db:
        row = db.execute("SELECT status FROM timeout_notices WHERE thread_id=?", (thread_id,)).fetchone()
        return row["status"] if row else None


def transition(thread_id, version, status, *, deadline=None, job_id=None):
    """CAS prevents stale continuations or timeout checks from reviving terminal tasks."""
    if status not in STATES or (status == "awaiting_clarification" and deadline is None):
        raise ValueError("Invalid status or missing clarification deadline")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        t = db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
        if (not t or t["version"] != version or t["status"] in TERMINAL
                or (t["status"] == "awaiting_clarification" and t["deadline"] <= time.time()
                    and status != "timed_out")):
            return None
        if t["job_id"] and job_id and t["job_id"] != job_id:
            raise ValueError("Job already assigned")
        db.execute("""UPDATE threads SET status=?, version=version+1, deadline=?,
            job_id=COALESCE(job_id,?) WHERE id=?""",
            (status, deadline if status == "awaiting_clarification" else None, job_id, thread_id))
        return _dict(db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone())
