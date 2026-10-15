"""Ruang Catat — versi Streamlit.

Jalankan lokal : streamlit run streamlit_app.py
Kata sandi (opsional): isi APP_PASSWORD di st.secrets
(Streamlit Cloud -> Settings -> Secrets).
"""

from __future__ import annotations

import hmac
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

DATABASE_PATH = Path(__file__).resolve().parent / "notes.db"
UNTITLED = "Catatan tanpa judul"
MAX_TITLE = 200
MAX_CONTENT = 500_000
WIB = timezone(timedelta(hours=7))  # ubah bila zona waktumu berbeda
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


# --------------------------------------------------------------------------
# Lapisan data (SQLite) — logikanya sama dengan server.py
# --------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:  # commit / rollback otomatis
            yield connection
    finally:
        connection.close()


def init_db() -> None:
    with db() as connection:
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


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def normalize_title(title: str) -> str:
    return title.strip() or UNTITLED


def list_notes(query: str = "") -> list[dict]:
    with db() as connection:
        if query:
            pattern = like_pattern(query)
            rows = connection.execute(
                """SELECT * FROM notes
                   WHERE title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\'
                   ORDER BY updated_at DESC, id DESC""",
                (pattern, pattern),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM notes ORDER BY updated_at DESC, id DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def get_note(note_id: int) -> dict | None:
    with db() as connection:
        row = connection.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else None


def create_note(title: str, content: str) -> dict:
    now = utc_now()
    with db() as connection:
        cursor = connection.execute(
            "INSERT INTO notes (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (normalize_title(title), content, now, now),
        )
        row = connection.execute(
            "SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def update_note(note_id: int, title: str, content: str) -> dict | None:
    with db() as connection:
        cursor = connection.execute(
            "UPDATE notes SET title = ?, content = ?, updated_at = ? WHERE id = ?",
            (normalize_title(title), content, utc_now(), note_id),
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row)


def delete_note(note_id: int) -> bool:
    with db() as connection:
        return connection.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount > 0


# --------------------------------------------------------------------------
# Helper tampilan
# --------------------------------------------------------------------------

def format_date(value: str) -> str:
    moment = datetime.fromisoformat(value).astimezone(WIB)
    if moment.date() == datetime.now(WIB).date():
        return f"Hari ini, {moment:%H.%M}"
    return f"{moment.day} {BULAN[moment.month - 1]}"


def md_safe(text: str) -> str:
    """Escape karakter Markdown agar judul/isi ditampilkan apa adanya."""
    return re.sub(r"([\\`*_\[\]~$:<>])", r"\\\1", text)


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def preview(content: str) -> str:
    return shorten(" ".join(content.split()), 60) or "Belum ada isi"


# --------------------------------------------------------------------------
# State & aksi (dipanggil sebagai callback tombol)
# --------------------------------------------------------------------------

def init_state() -> None:
    ss = st.session_state
    ss.setdefault("mode", "welcome")  # "welcome" | "editor"
    ss.setdefault("active_id", None)  # None = draf baru
    ss.setdefault("saved", {"title": "", "content": "", "updated_at": None})
    ss.setdefault("pending", None)  # navigasi yang menunggu konfirmasi
    ss.setdefault("confirm_delete", False)
    ss.setdefault("save_failed", False)


def is_dirty() -> bool:
    ss = st.session_state
    return ss.mode == "editor" and (
        ss.editor_title != ss.saved["title"] or ss.editor_content != ss.saved["content"]
    )


def open_editor(note_id: int | None) -> None:
    ss = st.session_state
    ss.pending = None
    ss.confirm_delete = False
    ss.save_failed = False
    if note_id is None:
        title, content, updated_at = "", "", None
    else:
        note = get_note(note_id)
        if note is None:
            ss.flash = ("error", "Catatan tidak ditemukan.")
            ss.mode, ss.active_id = "welcome", None
            return
        title, content, updated_at = note["title"], note["content"], note["updated_at"]
    ss.mode = "editor"
    ss.active_id = note_id
    ss.saved = {"title": title, "content": content, "updated_at": updated_at}
    ss.editor_title = title
    ss.editor_content = content


def request_open(note_id: int | None) -> None:
    """Buka catatan / draf baru; minta konfirmasi bila ada perubahan belum disimpan."""
    if is_dirty():
        st.session_state.pending = {"id": note_id}
    else:
        open_editor(note_id)


def discard_and_open() -> None:
    target = st.session_state.pending
    if target is not None:
        open_editor(target["id"])


def keep_editing() -> None:
    st.session_state.pending = None


def save_current() -> None:
    ss = st.session_state
    title, content = ss.editor_title.strip(), ss.editor_content
    if not title and not content.strip():
        ss.flash = ("error", "Tulis judul atau isi catatan terlebih dahulu.")
        return
    was_new = ss.active_id is None
    try:
        note = create_note(title, content) if was_new else update_note(ss.active_id, title, content)
    except sqlite3.Error:
        ss.save_failed = True
        ss.flash = ("error", "Catatan gagal disimpan. Coba lagi.")
        return
    if note is None:
        ss.save_failed = True
        ss.flash = ("error", "Catatan tidak ditemukan. Mungkin sudah dihapus.")
        return
    ss.active_id = note["id"]
    ss.saved = {"title": note["title"], "content": note["content"], "updated_at": note["updated_at"]}
    ss.editor_title = note["title"]
    ss.save_failed = False
    ss.flash = ("success", "Catatan berhasil disimpan." if was_new else "Perubahan catatan disimpan.")


def ask_delete() -> None:
    st.session_state.confirm_delete = True


def cancel_delete() -> None:
    st.session_state.confirm_delete = False


def do_delete() -> None:
    ss = st.session_state
    if ss.active_id is not None and delete_note(ss.active_id):
        ss.flash = ("success", "Catatan berhasil dihapus.")
    else:
        ss.flash = ("error", "Catatan tidak ditemukan.")
    ss.mode, ss.active_id = "welcome", None
    ss.confirm_delete = False
    ss.pending = None


# --------------------------------------------------------------------------
# Tampilan
# --------------------------------------------------------------------------

def require_password() -> None:
    """Gerbang kata sandi sederhana; aktif hanya bila APP_PASSWORD diisi di secrets."""
    try:
        expected = st.secrets.get("APP_PASSWORD")
    except Exception:
        expected = None
    if not expected or st.session_state.get("authed"):
        return
    st.title("Ruang Catat")
    entered = st.text_input("Kata sandi", type="password")
    if entered:
        if hmac.compare_digest(entered.encode(), str(expected).encode()):
            st.session_state.authed = True
            st.rerun()
        st.error("Kata sandi salah.")
    st.stop()


def render_sidebar() -> None:
    ss = st.session_state
    with st.sidebar:
        st.markdown("### 📝 ruang**catat**")
        st.caption("ruang untuk pikiranmu")
        st.button(
            "Catatan baru",
            icon=":material/add:",
            type="primary",
            width="stretch",
            on_click=request_open,
            args=(None,),
        )
        query = st.text_input(
            "Cari catatan",
            key="search",
            placeholder="Cari catatan… (tekan Enter)",
            label_visibility="collapsed",
        ).strip()
        notes = list_notes(query)
        st.caption(f"SEMUA CATATAN · {len(notes)}")
        if not notes:
            st.caption(
                "Catatan tidak ditemukan."
                if query
                else "Belum ada catatan. Mulai dengan menulis ide pertamamu."
            )
        for note in notes:
            active = ss.mode == "editor" and ss.active_id == note["id"]
            st.button(
                ("▸ " if active else "") + md_safe(shorten(note["title"], 40)),
                key=f"note_{note['id']}",
                width="stretch",
                on_click=request_open,
                args=(note["id"],),
            )
            st.caption(f"{md_safe(preview(note['content']))} · {format_date(note['updated_at'])}")
        st.divider()
        st.caption("Disimpan di server aplikasi ini")


def render_header() -> None:
    ss = st.session_state
    if ss.mode == "editor":
        fallback = "Catatan baru" if ss.active_id is None else UNTITLED
        title = ss.editor_title.strip() or fallback
    else:
        title = "Selamat datang"
    st.caption(f"Ruang pribadi  /  **{md_safe(title)}**")


def render_welcome() -> None:
    st.caption("TEMPAT IDE BERTUMBUH")
    st.title("Ruang kecil untuk pikiran besar.")
    st.write(
        "Mulai tulis apa pun yang sedang ada di pikiranmu. "
        "Ide, rencana, atau hal kecil yang ingin diingat."
    )
    st.button(
        "Tulis catatan pertama",
        icon=":material/add:",
        type="primary",
        on_click=request_open,
        args=(None,),
    )
    st.info(
        "Catatan tersimpan di server tempat aplikasi ini berjalan, bukan di perangkatmu. "
        "Pada hosting gratis, berkas catatan bisa ter-reset saat aplikasi restart."
    )


def render_editor() -> None:
    ss = st.session_state
    dirty = is_dirty()

    meta, status, delete, save = st.columns([3, 2, 1.3, 1.3], vertical_alignment="center")
    updated_at = ss.saved["updated_at"]
    meta.caption(f"Diperbarui {format_date(updated_at)}" if updated_at else "Catatan baru")
    if ss.save_failed:
        status.markdown("⚠️ **Gagal menyimpan**")
    elif dirty or ss.active_id is None:
        status.markdown("● **Belum disimpan**")
    else:
        status.markdown("✓ **Tersimpan**")
    if ss.active_id is not None:
        delete.button("Hapus", icon=":material/delete:", width="stretch", on_click=ask_delete)
    save.button(
        "Simpan",
        icon=":material/save:",
        type="primary",
        width="stretch",
        on_click=save_current,
    )

    if ss.pending is not None:
        st.warning("Perubahanmu belum disimpan. Buang perubahan dan pindah?")
        left, right = st.columns(2)
        left.button("Buang perubahan", on_click=discard_and_open)
        right.button("Tetap di editor", on_click=keep_editing)

    if ss.confirm_delete:
        name = md_safe(ss.saved["title"] or "catatan ini")
        st.warning(f"Hapus “{name}”? Catatan yang dihapus tidak dapat dipulihkan.")
        left, right = st.columns(2)
        left.button("Ya, hapus permanen", type="primary", on_click=do_delete)
        right.button("Batal", on_click=cancel_delete)

    st.text_input(
        "Judul catatan",
        key="editor_title",
        max_chars=MAX_TITLE,
        placeholder="Judul catatan",
        label_visibility="collapsed",
    )
    st.text_area(
        "Isi catatan",
        key="editor_content",
        height=420,
        max_chars=MAX_CONTENT,
        placeholder="Mulai menulis di sini...\n\nTidak perlu sempurna. Tulis saja dulu.",
        label_visibility="collapsed",
    )
    words = len(ss.editor_content.split())
    st.caption(f"{words} kata  ·  Perubahan teks diterapkan saat kolom ditinggalkan atau Ctrl+Enter")


def main() -> None:
    st.set_page_config(page_title="Ruang Catat", page_icon="📝", layout="wide")
    require_password()
    init_db()
    init_state()

    flash = st.session_state.pop("flash", None)
    if flash:
        st.toast(flash[1], icon="✅" if flash[0] == "success" else "⚠️")

    render_sidebar()
    render_header()
    if st.session_state.mode == "editor":
        render_editor()
    else:
        render_welcome()


if __name__ == "__main__":
    main()
