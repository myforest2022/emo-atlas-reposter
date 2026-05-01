"""
Модуль для публікації переписаних постів у Telegram-канал.

Логіка:
1. Беремо ОДИН пост зі статусом 'переписаний' з бази даних.
2. Якщо є media_path:
   а) файл є на диску → публікуємо напряму
   б) файл відсутній (ephemeral FS на Render) → повторно завантажуємо
      оригінал через Telethon за (channel, post_id) і публікуємо
3. Публікуємо rewritten_text у канал CHANNEL_ID.
4. Якщо є poll_question і poll_options — надсилаємо анонімне опитування.
5. Оновлюємо статус на 'опублікований'.
"""

import asyncio
import os

from telegram import Bot
from telegram.error import TelegramError

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import BOT_TOKEN, CHANNEL_ID, TELEGRAM_API_ID, TELEGRAM_API_HASH
from db.database import get_connection

# ─── Розширення для визначення типу медіа ────────────────────────────────────

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}

ROOT_DIR  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MEDIA_DIR = os.path.join(ROOT_DIR, "media")

# Сесія Telethon: StringSession з env (Render) або файл (локально)
_session_string = os.getenv("SESSION_STRING", "")
_TELETHON_SESSION = StringSession(_session_string) if _session_string else os.path.join(ROOT_DIR, "reposter_session")


def get_media_type(path: str) -> str:
    """Повертає 'photo', 'video' або 'none' за розширенням файлу."""
    if not path:
        return "none"
    ext = os.path.splitext(path)[1].lower()
    if ext in PHOTO_EXTENSIONS:
        return "photo"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "none"

# ─── Повторне завантаження медіа через Telethon ──────────────────────────────

async def redownload_media(channel: str, post_id: int, media_path: str) -> bool:
    """
    Завантажує медіа оригінального поста з source-каналу через Telethon.
    Використовується коли файл зник з диску (ephemeral FS на Render).
    Повертає True якщо файл успішно завантажено.
    """
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        print("⚠️  TELEGRAM_API_ID/HASH відсутні — повторне завантаження неможливе.")
        return False

    try:
        os.makedirs(MEDIA_DIR, exist_ok=True)
        async with TelegramClient(_TELETHON_SESSION, int(TELEGRAM_API_ID), TELEGRAM_API_HASH) as client:
            message = await client.get_messages(channel, ids=post_id)
            if message is None or not message.media:
                print(f"⚠️  Повідомлення {post_id} з {channel} не містить медіа.")
                return False
            await client.download_media(message.media, file=media_path)

        if os.path.isfile(media_path):
            print(f"♻️  Медіа повторно завантажено: {os.path.basename(media_path)}")
            return True

        print("⚠️  Файл не з'явився після повторного завантаження.")
        return False

    except Exception as e:
        print(f"⚠️  Не вдалося повторно завантажити медіа: {e}")
        return False

# ─── База даних ───────────────────────────────────────────────────────────────

def fetch_one_rewritten_post() -> dict | None:
    """
    Повертає один пост зі статусом 'переписаний' (найстаріший за id).
    poll_options зберігається як рядок через ||| — розбиваємо назад у список.
    """
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, post_id, channel, original_text, rewritten_text,
                      media_path, poll_question, poll_options
               FROM posts
               WHERE status = 'переписаний'
               ORDER BY id ASC
               LIMIT 1"""
        ).fetchone()

    if row is None:
        return None

    options_raw = row[7]
    poll_options = options_raw.split("|||") if options_raw else None

    return {
        "id":             row[0],
        "post_id":        row[1],
        "channel":        row[2],
        "original_text":  row[3],
        "rewritten_text": row[4],
        "media_path":     row[5],
        "poll_question":  row[6],
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
    1. Перевіряємо чи існує media_path на диску.
       Якщо файл зник (Render ephemeral FS) — повторно завантажуємо через Telethon.
    2. Надсилаємо текст (з фото/відео або без).
    3. Надсилаємо анонімне опитування якщо є.
    """
    bot = Bot(token=BOT_TOKEN)
    text       = post["rewritten_text"]
    media_path = post.get("media_path")
    channel    = post.get("channel", "")
    post_id    = post.get("post_id")

    print(f"[DEBUG] post_id    = {post.get('id')}")
    print(f"[DEBUG] media_path = {media_path}")

    # ── Перевірка наявності файлу; повторне завантаження якщо відсутній ────
    if media_path and get_media_type(media_path) != "none":
        if not os.path.isfile(media_path):
            print(f"⚠️  Файл не знайдено на диску: {media_path}")
            if channel and post_id:
                print(f"♻️  Спроба повторно завантажити з {channel} (msg_id={post_id})...")
                ok = await redownload_media(channel, post_id, media_path)
                if not ok:
                    print("⚠️  Повторне завантаження не вдалося — публікуємо тільки текст.")
                    media_path = None
            else:
                print("⚠️  channel або post_id відсутні — публікуємо тільки текст.")
                media_path = None
        else:
            print(f"[DEBUG] file_exists = True")

    media_type  = get_media_type(media_path) if media_path else "none"
    CAPTION_LIMIT = 1024

    async with bot:
        # ── 1. Публікація тексту (з медіа або без) ──────────────────────────
        if media_type == "photo":
            with open(media_path, "rb") as photo:
                if len(text) <= CAPTION_LIMIT:
                    await bot.send_photo(chat_id=CHANNEL_ID, photo=photo, caption=text)
                else:
                    await bot.send_photo(chat_id=CHANNEL_ID, photo=photo)
            if len(text) > CAPTION_LIMIT:
                await bot.send_message(chat_id=CHANNEL_ID, text=text)
                print(f"📷 Опубліковано фото + текст окремо (>{CAPTION_LIMIT} симв.): {media_path}")
            else:
                print(f"📷 Опубліковано з фото: {media_path}")

        elif media_type == "video":
            with open(media_path, "rb") as video:
                if len(text) <= CAPTION_LIMIT:
                    await bot.send_video(chat_id=CHANNEL_ID, video=video, caption=text)
                else:
                    await bot.send_video(chat_id=CHANNEL_ID, video=video)
            if len(text) > CAPTION_LIMIT:
                await bot.send_message(chat_id=CHANNEL_ID, text=text)
                print(f"🎬 Опубліковано відео + текст окремо (>{CAPTION_LIMIT} симв.): {media_path}")
            else:
                print(f"🎬 Опубліковано з відео: {media_path}")

        else:
            await bot.send_message(chat_id=CHANNEL_ID, text=text)
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
