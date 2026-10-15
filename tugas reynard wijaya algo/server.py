"""Server lokal untuk aplikasi Ruang Catat."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "notes.db"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    with connect_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def note_dict(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class NotesHandler(BaseHTTPRequestHandler):
    server_version = "RuangCatat/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                return None
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            return value if isinstance(value, dict) else None
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/notes":
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            with connect_db() as connection:
                if query:
                    rows = connection.execute(
                        """SELECT * FROM notes
                           WHERE title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\'
                           ORDER BY updated_at DESC, id DESC""",
                        (self.like_pattern(query), self.like_pattern(query)),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM notes ORDER BY updated_at DESC, id DESC"
                    ).fetchall()
            self.send_json(200, [note_dict(row) for row in rows])
            return

        if parsed.path.startswith("/api/notes/"):
            note_id = self.note_id(parsed.path)
            if note_id is None:
                self.send_json(400, {"error": "ID catatan tidak valid."})
                return
            with connect_db() as connection:
                row = connection.execute(
                    "SELECT * FROM notes WHERE id = ?", (note_id,)
                ).fetchone()
            if row is None:
                self.send_json(404, {"error": "Catatan tidak ditemukan."})
                return
            self.send_json(200, note_dict(row))
            return

        static = STATIC_FILES.get(parsed.path)
        if static is None:
            self.send_json(404, {"error": "Halaman tidak ditemukan."})
            return
        filename, content_type = static
        body = (BASE_DIR / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/notes":
            self.send_json(404, {"error": "Rute tidak ditemukan."})
            return
        data = self.read_json()
        if data is None:
            self.send_json(400, {"error": "Isi permintaan tidak valid."})
            return
        title, content, error = self.note_fields(data)
        if error:
            self.send_json(400, {"error": error})
            return
        now = utc_now()
        with connect_db() as connection:
            cursor = connection.execute(
                "INSERT INTO notes (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (title, content, now, now),
            )
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        self.send_json(201, note_dict(row))

    def do_PUT(self) -> None:
        note_id = self.note_id(urlparse(self.path).path)
        if note_id is None:
            self.send_json(400, {"error": "ID catatan tidak valid."})
            return
        data = self.read_json()
        if data is None:
            self.send_json(400, {"error": "Isi permintaan tidak valid."})
            return
        title, content, error = self.note_fields(data)
        if error:
            self.send_json(400, {"error": error})
            return
        with connect_db() as connection:
            existing = connection.execute(
                "SELECT id FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
            if existing is None:
                self.send_json(404, {"error": "Catatan tidak ditemukan."})
                return
            connection.execute(
                "UPDATE notes SET title = ?, content = ?, updated_at = ? WHERE id = ?",
                (title, content, utc_now(), note_id),
            )
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
        self.send_json(200, note_dict(row))

    def do_DELETE(self) -> None:
        note_id = self.note_id(urlparse(self.path).path)
        if note_id is None:
            self.send_json(400, {"error": "ID catatan tidak valid."})
            return
        with connect_db() as connection:
            cursor = connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        if cursor.rowcount == 0:
            self.send_json(404, {"error": "Catatan tidak ditemukan."})
            return
        self.send_json(200, {"deleted": True, "id": note_id})

    @staticmethod
    def note_id(path: str) -> int | None:
        prefix = "/api/notes/"
        if not path.startswith(prefix):
            return None
        try:
            value = int(path[len(prefix):])
            return value if value > 0 else None
        except ValueError:
            return None

    @staticmethod
    def note_fields(data: dict[str, object]) -> tuple[str, str, str | None]:
        title = data.get("title", "")
        content = data.get("content", "")
        if not isinstance(title, str) or not isinstance(content, str):
            return "", "", "Judul dan isi catatan harus berupa teks."
        if len(title) > 200:
            return "", "", "Judul maksimal 200 karakter."
        if len(content) > 500_000:
            return "", "", "Isi catatan terlalu panjang."
        return title.strip() or "Catatan tanpa judul", content, None

    @staticmethod
    def like_pattern(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Jalankan aplikasi catatan lokal.")
    parser.add_argument("--host", default="127.0.0.1", help="Alamat jaringan untuk server.")
    parser.add_argument("--port", type=int, default=8000, help="Port server (default: 8000).")
    args = parser.parse_args()
    initialize_db()
    server = ThreadingHTTPServer((args.host, args.port), NotesHandler)
    print(f"Ruang Catat aktif di http://{args.host}:{args.port}")
    print("Tekan Ctrl+C untuk menghentikan server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer dihentikan.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
