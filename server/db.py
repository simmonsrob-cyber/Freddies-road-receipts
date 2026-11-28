"""SQLite helpers and schema."""
import json
import sqlite3
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS person (
  id INTEGER PRIMARY KEY, full_name TEXT NOT NULL,
  aliases TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS trip (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', sent_at TEXT,
  start_date TEXT NOT NULL DEFAULT '', end_date TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS trip_member (
  trip_id INTEGER NOT NULL REFERENCES trip(id),
  person_id INTEGER NOT NULL REFERENCES person(id),
  PRIMARY KEY (trip_id, person_id));
CREATE TABLE IF NOT EXISTS batch (
  id INTEGER PRIMARY KEY, trip_id INTEGER NOT NULL REFERENCES trip(id),
  seq INTEGER NOT NULL, label TEXT, hotel_guess TEXT, hotel_final TEXT,
  date_guess TEXT, date_final TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS receipt (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batch(id),
  person_id INTEGER REFERENCES person(id), match_score REAL,
  status TEXT NOT NULL,  -- processing | matched | needs_review | confirmed
  tag TEXT NOT NULL DEFAULT 'Hotel', upload_date TEXT,
  inferred INTEGER NOT NULL DEFAULT 0, cands TEXT NOT NULL DEFAULT '[]', sugg TEXT NOT NULL DEFAULT '[]', note TEXT,
  original_path TEXT NOT NULL, scan_path TEXT, ocr_text TEXT,
  hotel_line TEXT, date_found TEXT, auto_crop INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learned_alias (
  person_id INTEGER NOT NULL REFERENCES person(id), alias TEXT NOT NULL,
  PRIMARY KEY (person_id, alias));
CREATE TABLE IF NOT EXISTS tag (name TEXT PRIMARY KEY, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS export (
  id INTEGER PRIMARY KEY, trip_id INTEGER NOT NULL, token TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    c = conn()
    c.executescript(SCHEMA)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(receipt)")}
    if "sugg" not in cols:   # database made by an older version: add the column, keep every row
        c.execute("ALTER TABLE receipt ADD COLUMN sugg TEXT NOT NULL DEFAULT '[]'")
    bcols = {r["name"] for r in c.execute("PRAGMA table_info(batch)")}
    tcols0 = {r["name"] for r in c.execute("PRAGMA table_info(trip)")}
    if "archived_at" not in tcols0:   # deleted missions are archived, never erased, until purged from Dev tools
        c.execute("ALTER TABLE trip ADD COLUMN archived_at TEXT NOT NULL DEFAULT ''")
    if "nona_required" not in bcols:   # older database: Non Availability is not required unless switched on
        c.execute("ALTER TABLE batch ADD COLUMN nona_required INTEGER NOT NULL DEFAULT 0")
    if "kind" not in bcols:   # older database: hotel stays stay hotel stays; "extras" holds Taxi/Non Availability/CNA
        c.execute("ALTER TABLE batch ADD COLUMN kind TEXT NOT NULL DEFAULT 'hotel'")
    tcols = {r["name"] for r in c.execute("PRAGMA table_info(trip)")}
    for col in ("start_date", "end_date"):   # older database: add the date columns, keep every mission
        if col not in tcols:
            c.execute("ALTER TABLE trip ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % col)
    if not c.execute("SELECT 1 FROM tag").fetchone():
        for i, t in enumerate(["Hotel", "NONA", "Taxi", "CNA"]):
            c.execute("INSERT INTO tag(name, sort) VALUES (?,?)", (t, i))
    if not c.execute("SELECT 1 FROM person").fetchone():   # first run: start with the Crew 4 names
        for n in config.PRESET_CREW:
            c.execute("INSERT INTO person(full_name) VALUES (?)", (n,))
    c.commit()
    c.close()


def state():
    """Everything the page needs, in one JSON-friendly dict."""
    c = conn()
    try:
        roster = [dict(id=r["id"], name=r["full_name"], aliases=r["aliases"], active=bool(r["active"]))
                  for r in c.execute("SELECT * FROM person ORDER BY full_name")]
        tags = [r["name"] for r in c.execute("SELECT name FROM tag ORDER BY sort, name")]
        members = {}
        for r in c.execute("SELECT * FROM trip_member"):
            members.setdefault(r["trip_id"], []).append(r["person_id"])
        recs = {}
        for r in c.execute("SELECT * FROM receipt ORDER BY id"):
            ver = int(r["id"]) * 1000 + (len(r["scan_path"] or "") and 1)
            recs.setdefault(r["batch_id"], []).append(dict(
                id=r["id"], pid=r["person_id"], status=r["status"], tag=r["tag"],
                date=r["upload_date"], inferred=bool(r["inferred"]), score=r["match_score"],
                cands=json.loads(r["cands"] or "[]"), sugg=json.loads(r["sugg"] or "[]"), text=r["ocr_text"] or "", note=r["note"] or "",
                autoCrop=None if r["auto_crop"] is None else bool(r["auto_crop"]),
                img="/img/%d?v=%s" % (r["id"], r["scan_path"] and _mtime(r["scan_path"]))))
        bats = {}
        for b in c.execute("SELECT * FROM batch ORDER BY seq"):
            bats.setdefault(b["trip_id"], []).append(dict(
                id=b["id"], label=b["label"] or "Batch %d" % b["seq"],
                hotelGuess=b["hotel_guess"] or "", hotelFinal=b["hotel_final"] or "",
                dateGuess=b["date_guess"] or "", dateFinal=b["date_final"] or "",
                kind=b["kind"] or "hotel", nonaRequired=bool(b["nona_required"]),
                receipts=recs.get(b["id"], [])))
        trips = [dict(id=t["id"], name=t["name"], status=t["status"], sentAt=t["sent_at"],
                      startDate=t["start_date"] or "", endDate=t["end_date"] or "",
                      archived=bool(t["archived_at"]), archivedAt=t["archived_at"] or "",
                      members=members.get(t["id"], []), batches=bats.get(t["id"], []))
                 for t in c.execute("SELECT * FROM trip ORDER BY id DESC")]
        return dict(version=config.VERSION, roster=roster, tags=tags, trips=trips)
    finally:
        c.close()


def _key(name):
    return " ".join("".join(ch if (ch.isalpha() or ch in "'-") else " " for ch in (name or "")).upper().split())


def person_id_for_name(c, name, create=True):
    """Find a person by name (ignoring case and punctuation). Creates them only when create=True; else returns None."""
    name = " ".join((name or "").split())
    k = _key(name)
    for r in c.execute("SELECT id, full_name FROM person"):
        if _key(r["full_name"]) == k:
            c.execute("UPDATE person SET active=1 WHERE id=?", (r["id"],))
            return r["id"]
    if not create:
        return None
    cur = c.execute("INSERT INTO person(full_name) VALUES (?)", (name,))
    return cur.lastrowid


def _mtime(path):
    try:
        import os
        return int(os.path.getmtime(path))
    except OSError:
        return 0
