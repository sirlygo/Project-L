"""Shared moderation, ticket, appeal, and analytics records for bot and dashboard."""

import json
import sqlite3
import time
from contextlib import closing

from config_loader import BASE_DIR

DB_PATH = BASE_DIR / "Data" / "dashboard.db"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS cases ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, "
        "member_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, "
        "action TEXT NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL);"
        "CREATE INDEX IF NOT EXISTS cases_member ON cases(guild_id,member_id,created_at);"
        "CREATE TABLE IF NOT EXISTS tickets ("
        "channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, "
        "kind TEXT NOT NULL, status TEXT NOT NULL, priority TEXT NOT NULL, "
        "assignee_id INTEGER, answers_json TEXT NOT NULL, "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);"
        "CREATE INDEX IF NOT EXISTS tickets_guild_status ON tickets(guild_id,status,updated_at);"
        "CREATE TABLE IF NOT EXISTS appeals ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, "
        "member_id INTEGER NOT NULL, case_id INTEGER, message TEXT NOT NULL, "
        "status TEXT NOT NULL, reviewer_id INTEGER, response TEXT, "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);"
        "CREATE INDEX IF NOT EXISTS appeals_guild_status ON appeals(guild_id,status,created_at);"
        "CREATE TABLE IF NOT EXISTS transcripts ("
        "channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, "
        "content TEXT NOT NULL, created_at INTEGER NOT NULL);"
        "CREATE INDEX IF NOT EXISTS transcripts_guild ON transcripts(guild_id,created_at);"
        "CREATE TABLE IF NOT EXISTS staff_notes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, "
        "subject_type TEXT NOT NULL, subject_id INTEGER NOT NULL, "
        "author_id INTEGER NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL);"
        "CREATE INDEX IF NOT EXISTS staff_notes_subject ON "
        "staff_notes(guild_id,subject_type,subject_id,created_at);"
        "CREATE TABLE IF NOT EXISTS config_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, "
        "actor_id INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at INTEGER NOT NULL);"
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(tickets)")}
    if "first_staff_response_at" not in columns:
        db.execute("ALTER TABLE tickets ADD COLUMN first_staff_response_at INTEGER")
    if "response_alerted_at" not in columns:
        db.execute("ALTER TABLE tickets ADD COLUMN response_alerted_at INTEGER")
    return db


def record_case(guild_id, member_id, moderator_id, action, reason):
    now = int(time.time())
    with closing(_connect()) as db, db:
        cursor = db.execute(
            "INSERT INTO cases(guild_id,member_id,moderator_id,action,reason,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (guild_id, member_id, moderator_id, action, reason[:1000], now),
        )
        return cursor.lastrowid


def safe_record_case(*args):
    try:
        return record_case(*args)
    except sqlite3.Error as exc:
        print(f"[!] Could not save moderation case: {exc}")
        return None


def list_cases(guild_id, *, member_id=None, limit=100):
    with closing(_connect()) as db:
        if member_id:
            rows = db.execute(
                "SELECT * FROM cases WHERE guild_id=? AND member_id=? "
                "ORDER BY id DESC LIMIT ?", (guild_id, member_id, min(limit, 200)),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM cases WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                (guild_id, min(limit, 200)),
            ).fetchall()
        return [dict(row) for row in rows]


def case_exists(guild_id, case_id):
    with closing(_connect()) as db:
        return db.execute("SELECT 1 FROM cases WHERE guild_id=? AND id=?",
                          (guild_id, case_id)).fetchone() is not None


def create_ticket_record(channel_id, guild_id, owner_id, kind, answers=None):
    now = int(time.time())
    with closing(_connect()) as db, db:
        db.execute(
            "INSERT OR IGNORE INTO tickets(channel_id,guild_id,owner_id,kind,status,priority,"
            "assignee_id,answers_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (channel_id, guild_id, owner_id, kind, "open", "normal", None,
             json.dumps(answers or {}, ensure_ascii=False), now, now),
        )


def update_ticket(channel_id, guild_id, *, status=None, priority=None, assignee_id=None):
    changes = []
    values = []
    for name, value in (("status", status), ("priority", priority), ("assignee_id", assignee_id)):
        if value is not None:
            changes.append(f"{name}=?")
            values.append(value)
    if not changes:
        return False
    values.extend((int(time.time()), channel_id, guild_id))
    with closing(_connect()) as db, db:
        cursor = db.execute(
            f"UPDATE tickets SET {', '.join(changes)},updated_at=? "
            "WHERE channel_id=? AND guild_id=?", values,
        )
        return cursor.rowcount > 0


def record_staff_response(channel_id, guild_id):
    """Record the first human staff reply without changing later response times."""
    with closing(_connect()) as db, db:
        cursor = db.execute(
            "UPDATE tickets SET first_staff_response_at=? WHERE channel_id=? AND guild_id=? "
            "AND first_staff_response_at IS NULL",
            (int(time.time()), channel_id, guild_id),
        )
        return cursor.rowcount > 0


def list_tickets(guild_id, *, status=None, search="", limit=100):
    query = "SELECT * FROM tickets WHERE guild_id=?"
    values = [guild_id]
    if status in {"open", "closed"}:
        query += " AND status=?"
        values.append(status)
    if search:
        query += " AND (CAST(channel_id AS TEXT) LIKE ? OR CAST(owner_id AS TEXT) LIKE ?)"
        values.extend((f"%{search}%", f"%{search}%"))
    query += " ORDER BY updated_at DESC LIMIT ?"
    values.append(min(limit, 200))
    with closing(_connect()) as db:
        rows = [dict(row) for row in db.execute(query, values)]
    for row in rows:
        row["answers"] = json.loads(row.pop("answers_json"))
    return rows


def ticket_exists(guild_id, channel_id):
    with closing(_connect()) as db:
        return db.execute(
            "SELECT 1 FROM tickets WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone() is not None


def get_ticket(guild_id, channel_id):
    with closing(_connect()) as db:
        row = db.execute(
            "SELECT * FROM tickets WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone()
    return dict(row) if row else None


def add_staff_note(guild_id, subject_type, subject_id, author_id, body):
    if subject_type not in {"ticket", "case"} or not str(body).strip():
        raise ValueError("Invalid staff note")
    with closing(_connect()) as db, db:
        return db.execute(
            "INSERT INTO staff_notes(guild_id,subject_type,subject_id,author_id,body,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (guild_id, subject_type, subject_id, author_id, str(body).strip()[:2000], int(time.time())),
        ).lastrowid


def list_staff_notes(guild_id, subject_type, subject_id):
    with closing(_connect()) as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM staff_notes WHERE guild_id=? AND subject_type=? AND subject_id=? "
            "ORDER BY id DESC LIMIT 100", (guild_id, subject_type, subject_id),
        )]


def record_config_snapshot(guild_id, actor_id, config):
    with closing(_connect()) as db, db:
        return db.execute(
            "INSERT INTO config_history(guild_id,actor_id,snapshot,created_at) VALUES(?,?,?,?)",
            (guild_id, actor_id, json.dumps(config, ensure_ascii=False), int(time.time())),
        ).lastrowid


def list_config_history(guild_id):
    with closing(_connect()) as db:
        return [dict(row) for row in db.execute(
            "SELECT id,guild_id,actor_id,created_at FROM config_history "
            "WHERE guild_id=? ORDER BY id DESC LIMIT 30", (guild_id,),
        )]


def purge_transcripts(guild_id, older_than):
    with closing(_connect()) as db, db:
        return db.execute(
            "DELETE FROM transcripts WHERE guild_id=? AND created_at<?", (guild_id, older_than),
        ).rowcount


def overdue_tickets(guild_id, target_minutes, now=None):
    if target_minutes <= 0:
        return []
    current = int(time.time()) if now is None else int(now)
    with closing(_connect()) as db:
        return [dict(row) for row in db.execute(
            "SELECT channel_id,owner_id,created_at,assignee_id FROM tickets WHERE guild_id=? "
            "AND status='open' AND first_staff_response_at IS NULL "
            "AND response_alerted_at IS NULL AND created_at<=? ORDER BY created_at LIMIT 20",
            (guild_id, current - target_minutes * 60),
        )]


def mark_response_alerted(guild_id, channel_id, now=None):
    current = int(time.time()) if now is None else int(now)
    with closing(_connect()) as db, db:
        return db.execute(
            "UPDATE tickets SET response_alerted_at=? WHERE guild_id=? AND channel_id=? "
            "AND response_alerted_at IS NULL",
            (current, guild_id, channel_id),
        ).rowcount > 0


def submit_appeal(guild_id, member_id, message, case_id=None):
    now = int(time.time())
    with closing(_connect()) as db, db:
        already_open = db.execute(
            "SELECT 1 FROM appeals WHERE guild_id=? AND member_id=? AND status='open'",
            (guild_id, member_id),
        ).fetchone()
        if already_open:
            return None
        if case_id is not None:
            owned_case = db.execute(
                "SELECT 1 FROM cases WHERE guild_id=? AND member_id=? AND id=?",
                (guild_id, member_id, case_id),
            ).fetchone()
            if not owned_case:
                raise ValueError("Case ID does not belong to this Discord account.")
        cursor = db.execute(
            "INSERT INTO appeals(guild_id,member_id,case_id,message,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (guild_id, member_id, case_id, message[:2000], "open", now, now),
        )
        return cursor.lastrowid


def list_appeals(guild_id, *, status=None, limit=100):
    query = "SELECT * FROM appeals WHERE guild_id=?"
    values = [guild_id]
    if status in {"open", "approved", "denied"}:
        query += " AND status=?"
        values.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    values.append(min(limit, 200))
    with closing(_connect()) as db:
        return [dict(row) for row in db.execute(query, values)]


def get_appeal(guild_id, appeal_id):
    with closing(_connect()) as db:
        row = db.execute(
            "SELECT * FROM appeals WHERE guild_id=? AND id=?",
            (guild_id, appeal_id),
        ).fetchone()
    return dict(row) if row else None


def review_appeal(guild_id, appeal_id, reviewer_id, status, response):
    if status not in {"approved", "denied"}:
        raise ValueError("invalid appeal status")
    with closing(_connect()) as db, db:
        cursor = db.execute(
            "UPDATE appeals SET status=?,reviewer_id=?,response=?,updated_at=? "
            "WHERE guild_id=? AND id=? AND status='open'",
            (status, reviewer_id, response[:2000], int(time.time()), guild_id, appeal_id),
        )
        return cursor.rowcount > 0


def overview(guild_id):
    with closing(_connect()) as db:
        counts = {}
        for table in ("cases", "tickets", "appeals"):
            counts[table] = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE guild_id=?", (guild_id,),
            ).fetchone()[0]
        counts["open_tickets"] = db.execute(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'", (guild_id,),
        ).fetchone()[0]
        counts["open_appeals"] = db.execute(
            "SELECT COUNT(*) FROM appeals WHERE guild_id=? AND status='open'", (guild_id,),
        ).fetchone()[0]
        counts["avg_first_response_seconds"] = db.execute(
            "SELECT CAST(AVG(first_staff_response_at-created_at) AS INTEGER) FROM tickets "
            "WHERE guild_id=? AND first_staff_response_at IS NOT NULL", (guild_id,),
        ).fetchone()[0]
        counts["cases_last_7_days"] = db.execute(
            "SELECT COUNT(*) FROM cases WHERE guild_id=? AND created_at>=?",
            (guild_id, int(time.time()) - 604800),
        ).fetchone()[0]
        counts["tickets_last_7_days"] = db.execute(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND created_at>=?",
            (guild_id, int(time.time()) - 604800),
        ).fetchone()[0]
    return counts


def save_transcript(guild_id, channel_id, content):
    with closing(_connect()) as db, db:
        db.execute(
            "INSERT OR REPLACE INTO transcripts(channel_id,guild_id,content,created_at) "
            "VALUES(?,?,?,?)",
            (channel_id, guild_id, str(content)[:2_000_000], int(time.time())),
        )


def search_transcripts(guild_id, term, limit=50):
    needle = str(term).strip()
    if len(needle) < 2:
        return []
    pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with closing(_connect()) as db:
        rows = db.execute(
            "SELECT channel_id,substr(content,max(1,instr(lower(content),lower(?))-80),240) "
            "AS excerpt,created_at FROM transcripts WHERE guild_id=? "
            "AND content LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT ?",
            (needle, guild_id, pattern, min(limit, 50)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_transcript(guild_id, channel_id):
    with closing(_connect()) as db:
        row = db.execute(
            "SELECT content FROM transcripts WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone()
    return row["content"] if row else None
