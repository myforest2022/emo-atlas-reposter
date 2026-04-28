import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "posts.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id        INTEGER,
                channel        TEXT,
                original_text  TEXT,
                rewritten_text TEXT,
                media_path     TEXT,
                date           TEXT,
                status         TEXT DEFAULT 'новий',
                poll_question  TEXT,
                poll_options   TEXT
            )
        """)
        # Унікальний індекс: один пост з одного каналу — один запис
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_post_channel
            ON posts (post_id, channel)
        """)
        # Міграція: додаємо колонки якщо таблиця вже існує без них.
        # ALTER TABLE ADD COLUMN ігнорує помилку якщо колонка вже є.
        for col, typedef in [
            ("poll_question", "TEXT"),
            ("poll_options",  "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE posts ADD COLUMN {col} {typedef}")
            except Exception:
                pass   # колонка вже існує — пропускаємо
        conn.commit()


def post_exists(post_id: int, channel: str) -> bool:
    """Повертає True якщо пост вже є в базі."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM posts WHERE post_id = ? AND channel = ?",
            (post_id, channel)
        ).fetchone()
    return row is not None


def save_post(post_id: int, channel: str, text: str,
              media_path: str, date: str) -> None:
    """Зберігає новий пост у базу зі статусом 'новий'."""
    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO posts
                (post_id, channel, original_text, media_path, date, status)
            VALUES (?, ?, ?, ?, ?, 'новий')
        """, (post_id, channel, text, media_path, date))
        conn.commit()


if __name__ == "__main__":
    init_db()
    print("База даних ініціалізована.")
