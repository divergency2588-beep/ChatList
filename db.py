"""Доступ к SQLite для ChatList."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DB_PATH = app_root() / "chatlist.db"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                prompt TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                api_url TEXT NOT NULL,
                api_id TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                prompt_id INTEGER,
                model_name TEXT NOT NULL,
                prompt_text TEXT NOT NULL,
                response_text TEXT NOT NULL,
                FOREIGN KEY (prompt_id) REFERENCES prompts(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                model_name TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT ''
            );
            """
        )
        self.conn.commit()
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        if self.conn.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 0:
            self.conn.executemany(
                """
                INSERT INTO models (name, api_url, api_id, is_active)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        "gpt-4o-mini",
                        "https://api.openai.com/v1/chat/completions",
                        "OPENAI_API_KEY",
                        0,
                    ),
                    (
                        "deepseek-chat",
                        "https://api.deepseek.com/v1/chat/completions",
                        "DEEPSEEK_API_KEY",
                        0,
                    ),
                    (
                        "llama-3.3-70b-versatile",
                        "https://api.groq.com/openai/v1/chat/completions",
                        "GROQ_API_KEY",
                        0,
                    ),
                ],
            )

        defaults = {
            "request_timeout": "60",
            "temperature": "0.7",
        }
        for key, value in defaults.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- prompts ---

    def add_prompt(self, prompt: str, tags: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO prompts (created_at, prompt, tags) VALUES (?, ?, ?)",
            (_now(), prompt, tags.strip()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_prompts(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM prompts ORDER BY id DESC"
        ).fetchall()

    def get_prompt(self, prompt_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM prompts WHERE id = ?", (prompt_id,)
        ).fetchone()

    def delete_prompt(self, prompt_id: int) -> None:
        self.conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        self.conn.commit()

    # --- models ---

    def list_models(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM models ORDER BY name COLLATE NOCASE"
        ).fetchall()

    def list_active_models(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM models WHERE is_active = 1 ORDER BY name COLLATE NOCASE"
        ).fetchall()

    def add_model(self, name: str, api_url: str, api_id: str, is_active: bool) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO models (name, api_url, api_id, is_active)
            VALUES (?, ?, ?, ?)
            """,
            (name.strip(), api_url.strip(), api_id.strip(), int(is_active)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_model(
        self,
        model_id: int,
        name: str,
        api_url: str,
        api_id: str,
        is_active: bool,
    ) -> None:
        self.conn.execute(
            """
            UPDATE models
            SET name = ?, api_url = ?, api_id = ?, is_active = ?
            WHERE id = ?
            """,
            (name.strip(), api_url.strip(), api_id.strip(), int(is_active), model_id),
        )
        self.conn.commit()

    def delete_model(self, model_id: int) -> None:
        self.conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
        self.conn.commit()

    def set_model_active(self, model_id: int, is_active: bool) -> None:
        self.conn.execute(
            "UPDATE models SET is_active = ? WHERE id = ?",
            (int(is_active), model_id),
        )
        self.conn.commit()

    # --- results ---

    def add_result(
        self,
        prompt_id: int | None,
        model_name: str,
        prompt_text: str,
        response_text: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO results
                (created_at, prompt_id, model_name, prompt_text, response_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_now(), prompt_id, model_name, prompt_text, response_text),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_results(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM results ORDER BY id DESC"
        ).fetchall()

    def delete_result(self, result_id: int) -> None:
        self.conn.execute("DELETE FROM results WHERE id = ?", (result_id,))
        self.conn.commit()

    # --- settings ---

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return default if row is None else str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def list_settings(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM settings ORDER BY key"
        ).fetchall()

    # --- logs ---

    def add_log(self, model_name: str, status: str, message: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO logs (created_at, model_name, status, message)
            VALUES (?, ?, ?, ?)
            """,
            (_now(), model_name, status, message),
        )
        self.conn.commit()

    def list_logs(self, limit: int = 200) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
