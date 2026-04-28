"""
Веб-панель репостера — двоколонковий темний інтерфейс.

Запуск із кореня проекту:
    python -m web.app
З телефону (локальна мережа):
    http://<IP-вашого-ПК>:5000
"""

import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import subprocess
from flask import (
    Flask, render_template, redirect, url_for,
    request, send_from_directory, jsonify
)

from db.database import get_connection
from ai.rewrite import rewrite_text, save_rewritten
from bot.publish import publish_post, mark_as_published

# ─── Ініціалізація ────────────────────────────────────────────────────────────

ROOT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MEDIA_DIR  = os.path.join(ROOT_DIR, "media")
CONFIG_PATH = os.path.join(ROOT_DIR, "config.py")

app = Flask(__name__, template_folder="templates")
app.secret_key = "reposter-panel-secret"

# ─── Кольори аватарів каналів ─────────────────────────────────────────────────

AVATAR_COLORS = [
    "#e91e8c",  # рожевий
    "#7c4dff",  # фіолетовий
    "#00bcd4",  # блакитний
    "#ff9800",  # помаранчевий
    "#4caf50",  # зелений
    "#f44336",  # червоний
    "#2196f3",  # синій
    "#ff5722",  # глибокий помаранчевий
]

def channel_color(name: str) -> str:
    """Детермінований колір аватара за назвою каналу."""
    return AVATAR_COLORS[sum(ord(c) for c in name) % len(AVATAR_COLORS)]

# ─── Читання / запис config.py ────────────────────────────────────────────────

def read_source_channels() -> list[str]:
    """
    Читає список SOURCE_CHANNELS з config.py без імпорту модуля.
    Парсить рядки вигляду:  SOURCE_CHANNELS = ["@a", "@b", ...]
    Повертає список рядків. При будь-якій помилці — порожній список.
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'SOURCE_CHANNELS\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if not m:
            return []
        return re.findall(r'["\']([^"\']+)["\']', m.group(1))
    except Exception:
        return []


def write_source_channels(channels: list[str]) -> None:
    """
    Перезаписує блок SOURCE_CHANNELS у config.py.
    Форматує список як багаторядковий з відступами.
    Зберігає решту файлу без змін.
    """
    with open(CONFIG_PATH, encoding="utf-8") as f:
        content = f.read()

    formatted = '[\n    ' + ',\n    '.join(f'"{ch}"' for ch in channels) + '\n]'
    new_content = re.sub(
        r'SOURCE_CHANNELS\s*=\s*\[.*?\]',
        f'SOURCE_CHANNELS = {formatted}',
        content,
        flags=re.DOTALL,
    )
    with open(CONFIG_PATH, 'w', encoding="utf-8") as f:
        f.write(new_content)

# ─── Допоміжні функції БД ────────────────────────────────────────────────────

def get_channels_with_stats() -> list[dict]:
    """
    Список каналів для лівої панелі.

    Джерела:
    1. SOURCE_CHANNELS з config.py — показуємо завжди, навіть якщо постів ще нема.
    2. Канали з БД яких нема в SOURCE_CHANNELS — показуємо в кінці (архів).

    Пости зі статусом 'ігнорувати' не враховуються.
    Сортування: спочатку канали з новими постами, потім решта.
    """
    source = read_source_channels()

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT channel,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'новий' THEN 1 ELSE 0 END) AS new_count
            FROM posts
            WHERE status != 'ігнорувати'
            GROUP BY channel
        """).fetchall()

    # Статистика з БД у вигляді словника
    db_stats: dict[str, dict] = {
        r[0]: {"total": r[1], "new_count": r[2] or 0} for r in rows
    }

    result: list[dict] = []
    seen: set[str] = set()

    # Спочатку — канали з SOURCE_CHANNELS (у порядку config.py)
    for ch in source:
        seen.add(ch)
        s = db_stats.get(ch, {"total": 0, "new_count": 0})
        result.append({
            "name":      ch,
            "total":     s["total"],
            "new_count": s["new_count"],
            "color":     channel_color(ch),
        })

    # Потім — архівні канали (є в БД, але вже не в SOURCE_CHANNELS)
    for ch, s in db_stats.items():
        if ch not in seen:
            result.append({
                "name":      ch,
                "total":     s["total"],
                "new_count": s["new_count"],
                "color":     channel_color(ch),
            })

    # Сортуємо: більше нових постів — вище
    result.sort(key=lambda x: (-x["new_count"], -x["total"]))
    return result


def fetch_channel_posts(channel: str) -> list[dict]:
    """
    Всі пости каналу (крім 'ігнорувати'), від нових до старих.
    Повертає список словників — буде серіалізовано в JSON.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, post_id, channel, original_text, rewritten_text, "
            "media_path, date, status, poll_question, poll_options FROM posts "
            "WHERE channel = ? AND status != 'ігнорувати' "
            "ORDER BY id DESC",
            (channel,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def fetch_post(db_id: int) -> dict | None:
    """Повертає один пост за внутрішнім id БД, або None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, post_id, channel, original_text, rewritten_text, "
            "media_path, date, status, poll_question, poll_options FROM posts WHERE id = ?",
            (db_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def _row_to_dict(row) -> dict:
    options_raw = row[9] if len(row) > 9 else None
    poll_options = options_raw.split("|||") if options_raw else None
    return {
        "id":             row[0],
        "post_id":        row[1],
        "channel":        row[2],
        "original_text":  row[3],
        "rewritten_text": row[4],
        "media_path":     row[5],
        "date":           row[6],
        "status":         row[7],
        "poll_question":  row[8] if len(row) > 8 else None,
        "poll_options":   poll_options,
    }


def save_edited_text(db_id: int, text: str) -> None:
    """
    Зберігає відредагований текст і переводить статус на 'переписаний'.
    Навіть якщо користувач просто вручну написав текст — вважаємо переписаним.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE posts SET rewritten_text = ?, status = 'переписаний' WHERE id = ?",
            (text, db_id)
        )
        conn.commit()


def set_status(db_id: int, status: str) -> None:
    """Встановлює статус посту (наприклад 'ігнорувати')."""
    with get_connection() as conn:
        conn.execute("UPDATE posts SET status = ? WHERE id = ?", (status, db_id))
        conn.commit()

# ─── Маршрути ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """
    Головна сторінка.
    Передає список каналів зі статистикою у шаблон.
    Перший канал автоматично підсвічується та завантажується через JS.
    """
    channels = get_channels_with_stats()
    return render_template("index.html", channels=channels)


@app.route("/post/<int:db_id>")
def post_detail(db_id: int):
    """Стара сторінка посту → редирект на головну (UI тепер однсторінковий)."""
    return redirect(url_for("index"))


@app.route("/api/posts/<channel>")
def api_posts(channel: str):
    """
    JSON-ендпоінт: пости одного каналу.
    Викликається клієнтським JS коли користувач вибирає канал у лівій панелі.
    """
    posts = fetch_channel_posts(channel)
    return jsonify(posts)


@app.route("/media/<path:filename>")
def serve_media(filename: str):
    """Роздає медіафайли з папки media/ (фото і відео для мініатюр у картках)."""
    return send_from_directory(MEDIA_DIR, filename)


@app.route("/post/<int:db_id>/remove-media", methods=["POST"])
def remove_media(db_id: int):
    """Видаляє медіа з посту — очищає media_path в БД."""
    with get_connection() as conn:
        conn.execute("UPDATE posts SET media_path = NULL WHERE id = ?", (db_id,))
        conn.commit()
    return jsonify({"ok": True})


@app.route("/post/<int:db_id>/upload-media", methods=["POST"])
def upload_media(db_id: int):
    """Завантажує нове фото для посту, зберігає в media/ і оновлює media_path в БД."""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Файл не знайдено"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "Файл не вибрано"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov"}
    if ext not in allowed:
        return jsonify({"ok": False, "error": "Непідтримуваний формат"}), 400
    filename = f"upload_{db_id}{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)
    file.save(filepath)
    with get_connection() as conn:
        conn.execute("UPDATE posts SET media_path = ? WHERE id = ?", (filepath, db_id))
        conn.commit()
    return jsonify({"ok": True, "media_path": filepath, "filename": filename})


@app.route("/post/<int:db_id>/ignore", methods=["POST"])
def ignore_post(db_id: int):
    """
    Кнопка "Видалити" в картці посту.
    Ставить статус 'ігнорувати' — пост зникає з усіх списків і не з'являється знову.
    Не видаляє запис фізично — можна буде знайти в БД вручну.
    """
    set_status(db_id, "ігнорувати")
    return jsonify({"ok": True})


@app.route("/post/<int:db_id>/save", methods=["POST"])
def save_text(db_id: int):
    """
    Зберігає відредагований текст та опитування з редактора.
    Приймає JSON: {"text": "...", "poll_question": "...", "poll_options": [...]}.
    Статус стає 'переписаний'.
    """
    data = request.get_json() or {}
    text          = (data.get("text") or "").strip()
    poll_question = (data.get("poll_question") or "").strip() or None
    opts_list     = data.get("poll_options") or []
    poll_options  = "|||".join(o.strip() for o in opts_list if o.strip()) or None

    with get_connection() as conn:
        conn.execute(
            "UPDATE posts SET rewritten_text = ?, status = 'переписаний', "
            "poll_question = ?, poll_options = ? WHERE id = ?",
            (text, poll_question, poll_options, db_id),
        )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/my-channel/post", methods=["POST"])
def my_channel_post():
    """
    Зберігає новий пост написаний вручну для власного каналу (@emo_atlas_ua).
    Приймає JSON: {"text": "...", "poll_question": "...", "poll_options": [...]}.
    Повертає: {"ok": true, "id": <db_id>}.
    """
    import datetime
    data = request.get_json() or {}
    text          = (data.get("text") or "").strip()
    poll_question = (data.get("poll_question") or "").strip() or None
    opts_list     = data.get("poll_options") or []
    poll_options  = "|||".join(o.strip() for o in opts_list if o.strip()) or None

    if not text:
        return jsonify({"ok": False, "error": "Текст порожній"}), 400

    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO posts (channel, original_text, rewritten_text, status, date, poll_question, poll_options) "
            "VALUES (?, ?, ?, 'переписаний', ?, ?, ?)",
            ("@emo_atlas_ua", text, text, now, poll_question, poll_options),
        )
        conn.commit()
        db_id = cur.lastrowid

    return jsonify({"ok": True, "id": db_id})


@app.route("/post/<int:db_id>/rewrite", methods=["POST"])
def rewrite(db_id: int):
    """
    Ручне переписування одного поста через Claude API.

    Логіка:
    - Фільтр реклами ПРИБРАНО — переписуємо будь-який текст.
    - Якщо текст порожній (пост лише з медіа) — повертаємо помилку.
    - Повертає JSON: {"ok": true, "text": "...", "emotion": "..."}.

    asyncio не потрібен — rewrite_text() синхронний через anthropic SDK.
    """
    post = fetch_post(db_id)
    if post is None:
        return jsonify({"ok": False, "error": "Пост не знайдено"}), 404

    original = (post["original_text"] or "").strip()
    if not original:
        return jsonify({"ok": False, "error": "Текст посту порожній — нема чого переписувати"}), 400

    try:
        result = rewrite_text(original)
        save_rewritten(
            db_id,
            result["text"],
            result.get("poll_question"),
            result.get("poll_options"),
        )
        return jsonify({
            "ok": True,
            "text": result["text"],
            "emotion": result["emotion"],
            "poll_question": result.get("poll_question"),
            "poll_options":  result.get("poll_options"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/post/<int:db_id>/publish", methods=["POST"])
def publish(db_id: int):
    """
    Публікує пост у Telegram-канал.

    asyncio.run() запускає async publish_post() з синхронного Flask-контексту.
    Потрібен тільки статус 'переписаний' — пост повинен мати текст для публікації.
    """
    post = fetch_post(db_id)
    if post is None:
        return jsonify({"ok": False, "error": "Пост не знайдено"}), 404

    if post["status"] != "переписаний":
        return jsonify({
            "ok": False,
            "error": f"Публікація недоступна зі статусом «{post['status']}»"
        }), 400

    if not (post["rewritten_text"] or "").strip():
        return jsonify({"ok": False, "error": "Переписаний текст порожній"}), 400

    try:
        asyncio.run(publish_post(post))
        mark_as_published(db_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/rewrite-all", methods=["POST"])
def rewrite_all():
    """
    Переписує всі пости зі статусом 'новий' для вказаного каналу.

    Приймає JSON: {"channel": "@назва_каналу"}.
    Якщо channel відсутній — переписує всі нові пости в усіх каналах.

    Повертає: {"ok": true, "count": N, "errors": [...]}.
    Помилки на окремих постах не зупиняють обробку решти.
    """
    data = request.get_json() or {}
    channel = data.get("channel")

    with get_connection() as conn:
        if channel:
            rows = conn.execute(
                "SELECT id, original_text FROM posts "
                "WHERE channel = ? AND status = 'новий'",
                (channel,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, original_text FROM posts WHERE status = 'новий'"
            ).fetchall()

    count, errors = 0, []
    for db_id, original in rows:
        if not (original or "").strip():
            continue
        try:
            result = rewrite_text(original)
            save_rewritten(
                db_id,
                result["text"],
                result.get("poll_question"),
                result.get("poll_options"),
            )
            count += 1
        except Exception as e:
            errors.append(str(e))

    return jsonify({"ok": True, "count": count, "errors": errors})


@app.route("/channels/add", methods=["POST"])
def add_channel():
    """
    Додає канал до SOURCE_CHANNELS в config.py.
    Приймає JSON: {"channel": "@назва"}.
    Автоматично додає @ якщо відсутній.
    Повертає: {"ok": true, "channel": "@назва", "color": "#hex"}.
    """
    data    = request.get_json() or {}
    channel = (data.get("channel") or "").strip()
    if not channel:
        return jsonify({"ok": False, "error": "Назва каналу порожня"}), 400
    if not channel.startswith("@"):
        channel = "@" + channel

    channels = read_source_channels()
    if channel in channels:
        return jsonify({"ok": False, "error": f"Канал {channel} вже є в списку"}), 400

    channels.append(channel)
    write_source_channels(channels)
    return jsonify({"ok": True, "channel": channel, "color": channel_color(channel)})


@app.route("/channels/remove", methods=["POST"])
def remove_channel():
    """
    Видаляє канал з SOURCE_CHANNELS в config.py.
    Приймає JSON: {"channel": "@назва"}.
    Пости в БД НЕ видаляються — залишаються як архів.
    """
    data    = request.get_json() or {}
    channel = (data.get("channel") or "").strip()
    if not channel:
        return jsonify({"ok": False, "error": "Назва каналу порожня"}), 400

    channels = read_source_channels()
    if channel not in channels:
        return jsonify({"ok": False, "error": f"Канал {channel} не знайдено в config.py"}), 404

    channels.remove(channel)
    write_source_channels(channels)
    return jsonify({"ok": True})


@app.route("/run-parser", methods=["POST"])
def run_parser():
    """
    Запускає parser/fetch.py у фоновому subprocess.

    Чому subprocess, а не прямий виклик:
    - Парсер використовує asyncio + Telethon з власним event loop.
    - Subprocess ізолює його від Flask і не блокує веб-сервер.
    - Відповідь повертається одразу, парсер працює у фоні.
    """
    try:
        script = os.path.join(ROOT_DIR, "parser", "fetch.py")
        subprocess.Popen(
            [sys.executable, script],
            cwd=ROOT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─── Запуск ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # host="0.0.0.0" — доступний з телефону через локальну Wi-Fi (http://<IP>:5000)
    app.run(host="0.0.0.0", port=5000, debug=True)
