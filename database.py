import sqlite3, os

DB = "aria_brain.db"

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            question  TEXT NOT NULL,
            def       TEXT,
            exp       TEXT,
            example   TEXT,
            tip       TEXT,
            subject   TEXT DEFAULT 'general',
            weight    REAL DEFAULT 1.0,
            uses      INTEGER DEFAULT 0,
            created   INTEGER,
            updated   INTEGER
        );
        CREATE TABLE IF NOT EXISTS facts (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            text    TEXT NOT NULL,
            subject TEXT DEFAULT 'general',
            weight  REAL DEFAULT 1.0,
            uses    INTEGER DEFAULT 0,
            created INTEGER
        );
        CREATE TABLE IF NOT EXISTS corrections (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            wrong   TEXT,
            right   TEXT,
            question TEXT,
            time    INTEGER
        );
        CREATE TABLE IF NOT EXISTS api_calls (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            time    INTEGER
        );
    """)
    conn.commit()
    conn.close()