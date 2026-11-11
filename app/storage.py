"""SQLite persistence (local-first). Not encrypted at rest: see PRIVACY_AND_SECURITY.md."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, title TEXT, profile TEXT, mode TEXT, settings TEXT, consent TEXT,
  status TEXT, record_audio INTEGER, audio_path TEXT, started_at REAL, ended_at REAL, summary TEXT);
CREATE TABLE IF NOT EXISTS utterances(
  id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE, seq INTEGER,
  ts_ms INTEGER, speaker TEXT, text TEXT, source TEXT, proc_ms REAL);
CREATE TABLE IF NOT EXISTS events(
  id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE, utterance_id TEXT,
  type TEXT, confidence REAL, payload TEXT);
CREATE TABLE IF NOT EXISTS interventions(
  id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE, utterance_id TEXT,
  event_type TEXT, priority TEXT, status TEXT, title TEXT, body TEXT, evidence TEXT, confidence REAL,
  score REAL, decision TEXT, trigger TEXT, ts_ms INTEGER, feedback TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, session_id TEXT, name TEXT, text TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS usage(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
  kind TEXT, provider TEXT, cloud INTEGER, tokens_in INTEGER, tokens_out INTEGER, created_at REAL);
CREATE INDEX IF NOT EXISTS ix_utt ON utterances(session_id, seq);
CREATE INDEX IF NOT EXISTS ix_int ON interventions(session_id, created_at);
"""
JSON_COLS = {"settings", "consent", "summary", "payload", "evidence", "decision"}


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class Storage:
    def __init__(self, path: str | Path, audio_dir: str | Path | None = None):
        self.path = str(path)
        self.audio_dir = Path(audio_dir) if audio_dir else Path(self.path).parent / "audio"
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    # -- helpers
    def _x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    @staticmethod
    def _row(r):
        d = dict(r)
        for k in JSON_COLS & d.keys():
            d[k] = json.loads(d[k]) if d[k] else None
        return d

    def _q(self, sql, args=()):
        with self.lock:
            return [self._row(r) for r in self.conn.execute(sql, args).fetchall()]

    # -- sessions
    def create_session(self, title, profile, mode, settings, consent, record_audio) -> dict:
        sid = _uid()
        self._x("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, title, profile, mode, json.dumps(settings), json.dumps(consent), "active",
                 int(record_audio), None, time.time(), None, None))
        return self.get_session(sid)

    def get_session(self, sid):
        r = self._q("SELECT * FROM sessions WHERE id=?", (sid,))
        return r[0] if r else None

    def update_session(self, sid, **kw):
        for k, v in kw.items():
            if k in JSON_COLS:
                v = json.dumps(v)
            self._x(f"UPDATE sessions SET {k}=? WHERE id=?", (v, sid))

    def list_sessions(self, q: str | None = None):
        if q:
            like = f"%{q}%"
            return self._q("""SELECT DISTINCT s.id,s.title,s.profile,s.mode,s.status,s.started_at,s.ended_at FROM sessions s
              LEFT JOIN utterances u ON u.session_id=s.id WHERE s.title LIKE ? OR u.text LIKE ?
              ORDER BY s.started_at DESC""", (like, like))
        return self._q("SELECT id,title,profile,mode,status,started_at,ended_at FROM sessions ORDER BY started_at DESC")

    def delete_session(self, sid) -> bool:
        s = self.get_session(sid)
        if not s:
            return False
        if s["audio_path"]:
            try:
                os.remove(s["audio_path"])
            except FileNotFoundError:
                pass
        self._x("DELETE FROM documents WHERE session_id=?", (sid,))
        self._x("DELETE FROM sessions WHERE id=?", (sid,))
        return True

    def purge_older_than(self, days: int) -> int:
        cutoff = time.time() - days * 86400
        old = self._q("SELECT id FROM sessions WHERE started_at<?", (cutoff,))
        for o in old:
            self.delete_session(o["id"])
        return len(old)

    # -- utterances / events / interventions
    def add_utterance(self, sid, seq, ts_ms, speaker, text, source, proc_ms=None) -> dict:
        uid = _uid()
        self._x("INSERT INTO utterances VALUES(?,?,?,?,?,?,?,?)", (uid, sid, seq, ts_ms, speaker, text, source, proc_ms))
        return {"id": uid, "session_id": sid, "seq": seq, "ts_ms": ts_ms, "speaker": speaker, "text": text, "source": source}

    def set_proc_ms(self, uid, ms):
        self._x("UPDATE utterances SET proc_ms=? WHERE id=?", (ms, uid))

    def utterances(self, sid):
        return self._q("SELECT * FROM utterances WHERE session_id=? ORDER BY seq", (sid,))

    def add_event(self, sid, utt_id, etype, conf, payload):
        eid = _uid()
        self._x("INSERT INTO events VALUES(?,?,?,?,?,?)", (eid, sid, utt_id, etype, conf, json.dumps(payload)))
        return eid

    def events(self, sid):
        return self._q("SELECT * FROM events WHERE session_id=?", (sid,))

    def add_intervention(self, sid, utt_id, event_type, priority, status, title, body, evidence, confidence,
                         score, decision, trigger, ts_ms) -> dict:
        iid = _uid()
        self._x("INSERT INTO interventions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, sid, utt_id, event_type, priority, status, title, body, json.dumps(evidence), confidence,
                 score, json.dumps(decision), trigger, ts_ms, None, time.time()))
        return self.get_intervention(iid)

    def get_intervention(self, iid):
        r = self._q("SELECT * FROM interventions WHERE id=?", (iid,))
        return r[0] if r else None

    def update_intervention(self, iid, **kw):
        for k, v in kw.items():
            self._x(f"UPDATE interventions SET {k}=? WHERE id=?", (v, iid))

    def interventions(self, sid):
        return self._q("SELECT * FROM interventions WHERE session_id=? ORDER BY created_at, rowid", (sid,))

    # -- documents
    def add_document(self, name, text, session_id=None) -> dict:
        did = _uid()
        self._x("INSERT INTO documents VALUES(?,?,?,?,?)", (did, session_id, name, text, time.time()))
        return {"id": did, "name": name, "session_id": session_id}

    def documents(self, sid=None):
        return self._q("SELECT * FROM documents WHERE session_id IS NULL OR session_id=?", (sid,))

    # -- usage
    def add_usage(self, sid, kind, provider, cloud, tin, tout):
        self._x("INSERT INTO usage(session_id,kind,provider,cloud,tokens_in,tokens_out,created_at) VALUES(?,?,?,?,?,?,?)",
                (sid, kind, provider, int(cloud), tin, tout, time.time()))

    def usage(self, sid):
        return self._q("SELECT * FROM usage WHERE session_id=?", (sid,))
