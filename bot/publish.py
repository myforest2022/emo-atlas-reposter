"""
Модуль для публікації переписаних постів у Telegram-канал.

Логіка:
1. Беремо ОДИН пост зі статусом 'переписаний' з бази даних.
2. Якщо є media_path — визначаємо тип (фото / відео) і прикріплюємо до посту.
3. Публікуємо rewritten_text у канал CHANNEL_ID.
4. Якщо є poll_question і poll_options — надсилаємо анонімне опитування.
5. Оновлюємо статус на 'опублікований'.
6. Виводимо результат у термінал.

Запуск: python -m bot.publish
Щоб опублікувати наступний пост — запускайте знову.
"""

import asyncio
import os

from telegram import Bot
from telegram.error import TelegramError

from config import BOT_TOKEN, CHANNEL_ID
from db.database import get_connection

# ─── Розширення для визначення типу медіа ────────────────────────────────────

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}


def get_media_type(path: str) -> str:
    """
    Повертає 'photo', 'video' або 'none' за розширенням файлу.
    Повертає 'none' якщо файл не існує на диску.
    """
    if not path or not os.path.isfile(path):
        return "none"

    ext = os.path.splitext(path)[1].lower()
    if ext in PHOTO_EXTENSIONS:
        return "photo"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "none"

# ─── База даних ───────────────────────────────────────────────────────────────

def fetch_one_rewritten_post() -> dict | None:
    """
    Повертає один пост зі статусом 'переписаний' (найстаріший за id).
    Повертає None якщо таких постів немає.

    poll_options зберігається як рядок через ||| — розбиваємо назад у список.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, channel, original_text, rewritten_text,
                      media_path, poll_question, poll_options
               FROM posts
               WHERE status = 'переписаний'
               ORDER BY id ASC
               LIMIT 1"""
        ).fetchone()

    if row is None:
        return None

    options_raw = row[6]
    poll_options = options_raw.split("|||") if options_raw else None

    return {
        "id":             row[0],
        "channel":        row[1],
        "original_text":  row[2],
        "rewritten_text": row[3],
        "media_path":     row[4],
        "poll_question":  row[5],
        "poll_options":   poll_options,
    }


def mark_as_published(post_id: int) -> None:
    """Оновлює статус посту на 'опублікований'."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE posts SET status = 'опублікований' WHERE id = ?",
            (post_id,),
        )
        conn.commit()

# ─── Публікація ───────────────────────────────────────────────────────────────

async def publish_post(post: dict) -> None:
    """
    Публікує один пост у Telegram-канал.

    Послідовність:
    1. Надсилаємо текст (з фото/відео або без).
       - Якщо є фото → send_photo(caption=text)
       - Якщо є відео → send_video(caption=text)
       - Без медіа    → send_message(text)
    2. Якщо є poll_question і poll_options (4 варіанти) →
       надсилаємо анонімне опитування send_poll():
       - is_anonymous=True  — читач не бачить хто як проголосував
       - allows_multiple_answers=False — один вибір
       Опитування йде окремим повідомленням після тексту,
       тому читач спочатку отримує контекст, а потім може
       відрефлексувати свій стан через голосування.
    """
    bot = Bot(token=BOT_TOKEN)
    text = post["rewritten_text"]
    media_type = get_media_type(post.get("media_path"))

    async with bot:
        # ── 1. Публікація тексту (з медіа або без) ──────────────────────────
        if media_type == "photo":
            with open(post["media_path"], "rb") as photo:
                await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=photo,
                    caption=text,
                )
            print(f"📷 Опубліковано з фото: {post['media_path']}")

        elif media_type == "video":
            with open(post["media_path"], "rb") as video:
                await bot.send_video(
                    chat_id=CHANNEL_ID,
                    video=video,
                    caption=text,
                )
            print(f"🎬 Опубліковано з відео: {post['media_path']}")

        else:
            if post.get("media_path") and media_type == "none":
                print(f"⚠️  Медіафайл не знайдено: {post['media_path']} — публікуємо тільки текст.")
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
            )
            print("💬 Опубліковано текстовий пост.")

        # ── 2. Анонімне опитування (якщо є дані) ────────────────────────────
        question = post.get("poll_question")
        options  = post.get("poll_options")

        if question and options and len(options) >= 2:
            await bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question,
                options=options,
                is_anonymous=True,
                allows_multiple_answers=False,
            )
            print(f"📊 Опитування надіслано: «{question}»")
        else:
            print("ℹ️  Опитування відсутнє — пропускаємо.")

# ─── Головна функція ──────────────────────────────────────────────────────────

def run_publisher() -> None:
    """
    Бере один переписаний пост, публікує його і позначає як опублікований.
    Щоб опублікувати наступний — запустіть скрипт ще раз.
    """
    post = fetch_one_rewritten_post()

    if post is None:
        print("Немає переписаних постів для публікації.")
        return

    print(f"{'─' * 60}")
    print(f"Публікую пост ID={post['id']} з каналу {post['channel']}")
    print(f"\n📄 Текст:\n{post['rewritten_text']}")
    if post.get("poll_question"):
        print(f"\n📊 Питання: {post['poll_question']}")
        for i, opt in enumerate(post.get("poll_options") or [], start=1):
            print(f"   {i}. {opt}")
    print()

    try:
        asyncio.run(publish_post(post))
        mark_as_published(post["id"])
        print(f"✅ Пост ID={post['id']} успішно опублікований у {CHANNEL_ID}.")
    except TelegramError as e:
        print(f"❌ Помилка Telegram API: {e}")
    except Exception as e:
        print(f"❌ Несподівана помилка: {e}")

    print(f"{'─' * 60}")


if __name__ == "__main__":
    run_publisher()
