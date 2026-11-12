"""Histórico SQLite por sessão, com exportação incremental e filtros temporais."""
import csv
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .protocol import Sample

COLUMNS = ("t_s", "va_V", "vb_V", "vc_V", "ia_A", "ib_A", "ic_A", "origem")
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
 id INTEGER PRIMARY KEY, started_utc TEXT NOT NULL, ended_utc TEXT,
 source TEXT NOT NULL, calibration_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS samples (
 session_id INTEGER NOT NULL REFERENCES sessions(id), t REAL NOT NULL,
 va REAL NOT NULL, vb REAL NOT NULL, vc REAL NOT NULL,
 ia REAL, ib REAL, ic REAL, PRIMARY KEY(session_id, t));
"""


class SqliteRecorder:
    def __init__(self, path: Path, source: str, calibration_json: str = "{}") -> None:
        self.path, self.source, self.count = Path(path), source, 0
        self._db = sqlite3.connect(path)
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(SCHEMA)
            cursor = self._db.execute(
                "INSERT INTO sessions(started_utc, source, calibration_json) VALUES (?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), source, calibration_json))
            self.session_id = cursor.lastrowid
            self._db.commit()
        except sqlite3.Error:
            self._db.close()
            raise

    def write(self, sample: Sample) -> None:
        self._db.execute("INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (self.session_id, sample.t, sample.va, sample.vb, sample.vc, sample.ia, sample.ib, sample.ic))
        self.count += 1

    def flush(self) -> None:
        self._db.commit()

    def close(self) -> None:
        try:
            self._db.execute("UPDATE sessions SET ended_utc=? WHERE id=?",
                             (datetime.now(timezone.utc).isoformat(), self.session_id))
            self._db.commit()
        finally:
            self._db.close()


def open_history(path: Path) -> sqlite3.Connection:
    # URI read-only impede criar um banco vazio por engano.
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("SELECT id, started_utc, ended_utc, source, calibration_json FROM sessions LIMIT 1")
        connection.execute("SELECT session_id, t, va, vb, vc, ia, ib, ic FROM samples LIMIT 1")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def list_sessions(path: Path) -> list[tuple]:
    db = open_history(path)
    try:
        return db.execute("""SELECT s.id, s.started_utc, s.source, COUNT(a.t), s.ended_utc
             FROM sessions s LEFT JOIN samples a ON s.id=a.session_id
             GROUP BY s.id ORDER BY s.id DESC""").fetchall()
    finally:
        db.close()


def export_session(path: Path, session_id: int, output: Path,
                   start_s: float | None = None, end_s: float | None = None) -> int:
    if Path(path).resolve() == Path(output).resolve():
        raise ValueError("O CSV não pode substituir o banco de histórico")
    db = open_history(path)
    try:
        if not db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
            raise ValueError("Sessão inexistente")
        query = """SELECT t, va, vb, vc, ia, ib, ic, source FROM samples
                   JOIN sessions ON sessions.id=samples.session_id WHERE session_id=?"""
        parameters: list = [session_id]
        if start_s is not None:
            query += " AND t>=?"
            parameters.append(start_s)
        if end_s is not None:
            query += " AND t<=?"
            parameters.append(end_s)
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(COLUMNS)
            count = 0
            for row in db.execute(query + " ORDER BY t", parameters):
                writer.writerow(row)
                count += 1
        return count
    finally:
        db.close()
