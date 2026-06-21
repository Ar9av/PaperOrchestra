#!/usr/bin/env python3
"""Cross-run Semantic Scholar cache and rate limiter backed by SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path


def norm_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cache_entries (
            key TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limit (
            bucket TEXT PRIMARY KEY,
            next_allowed REAL NOT NULL
        )
        """
    )
    return connection


def load_cached_response(db_path: Path, title: str) -> dict | None:
    connection = _connect(db_path)
    try:
        row = connection.execute(
            "SELECT response_json FROM cache_entries WHERE key = ?",
            (norm_key(title),),
        ).fetchone()
        if not row:
            return None
        return json.loads(row[0])
    finally:
        connection.close()


def store_cached_response(db_path: Path, title: str, response: dict) -> None:
    connection = _connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO cache_entries(key, response_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                response_json = excluded.response_json,
                updated_at = excluded.updated_at
            """,
            (norm_key(title), json.dumps(response, ensure_ascii=False), time.time()),
        )
    finally:
        connection.close()


def wait_for_rate_limit(db_path: Path, interval_seconds: float = 1.0, bucket: str = "semantic_scholar") -> None:
    interval = max(interval_seconds, 0.0)
    while True:
        connection = _connect(db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT next_allowed FROM rate_limit WHERE bucket = ?",
                (bucket,),
            ).fetchone()
            now = time.time()
            next_allowed = float(row[0]) if row else 0.0
            if now >= next_allowed:
                connection.execute(
                    """
                    INSERT INTO rate_limit(bucket, next_allowed)
                    VALUES(?, ?)
                    ON CONFLICT(bucket) DO UPDATE SET
                        next_allowed = excluded.next_allowed
                    """,
                    (bucket, now + interval),
                )
                connection.commit()
                return
            wait_seconds = next_allowed - now
            connection.rollback()
        finally:
            connection.close()
        time.sleep(wait_seconds)
