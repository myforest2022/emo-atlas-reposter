"""
Парсер постів із Telegram-каналів за допомогою Telethon.

Як запустити:
    python parser/fetch.py

При першому запуску Telethon попросить:
    1. Ввести номер телефону (у форматі +380XXXXXXXXX)
    2. Ввести код підтвердження з Telegram
    3. Якщо увімкнена 2FA — пароль
Сесія зберігається у файл reposter_session.session — наступні запуски
не потребуватимуть авторизації.
"""

import asyncio
import os
import sys

# Дозволяє запускати файл з будь-якої папки
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, SOURCE_CHANNELS
from db.database import init_db, post_exists, save_post

# Кількість постів, які забираємо з кожного каналу
POSTS_LIMIT = 2

# Папка для медіафайлів
MEDIA_DIR = os.path.join(os.path.dirname(__file__), "..", "media")

# Файл сесії Telethon (зберігається поруч із скриптом)
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "reposter_session")

# На Render використовуємо SESSION_STRING зі змінної середовища;
# локально — файл reposter_session.session
_session_string = os.getenv("SESSION_STRING", "")
SESSION = StringSession(_session_string) if _session_string else SESSION_FILE


async def download_media(client: TelegramClient, message, channel: str) -> str | None:
    """
    Скачує фото або відео з повідомлення у папку media/.
    Повертає шлях до файлу або None якщо медіа немає.
    """
    if not message.media:
        return None

    is_photo = isinstance(message.media, MessageMediaPhoto)
    is_video = (
        isinstance(message.media, MessageMediaDocument)
        and message.media.document.mime_type.startswith("video/")
    )

    if not (is_photo or is_video):
        return None

    # Ім'я файлу: назва_каналу_id_посту.jpg/mp4
    ext = "jpg" if is_photo else "mp4"
    filename = f"{channel.lstrip('@')}_{message.id}.{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)

    print(f"    Завантажую медіа → {filename}")
    await client.download_media(message.media, file=filepath)
    return filepath


async def fetch_from_channel(client: TelegramClient, channel: str) -> None:
    """Читає останні POSTS_LIMIT постів із каналу і зберігає нові в БД."""
    print(f"\n{'─' * 50}")
    print(f"Канал: {channel}")
    print(f"{'─' * 50}")

    try:
        saved = 0
        skipped = 0

        async for message in client.iter_messages(channel, limit=POSTS_LIMIT):
            # Пропускаємо повідомлення без тексту і без медіа
            if not message.text and not message.media:
                continue

            post_id = message.id
            text = message.text or ""
            date_str = message.date.strftime("%Y-%m-%d %H:%M:%S")

            # Перевірка на дублікат
            if post_exists(post_id, channel):
                print(f"  [пропущено]  id={post_id}  (вже є в базі)")
                skipped += 1
                continue

            # Скачування медіа якщо є
            media_path = await download_media(client, message, channel)

            # Збереження в БД
            save_post(
                post_id=post_id,
                channel=channel,
                text=text,
                media_path=media_path,
                date=date_str,
            )

            preview = text[:60].replace("\n", " ") if text else "[тільки медіа]"
            print(f"  [збережено]  id={post_id}  {preview}...")
            saved += 1

        print(f"  Підсумок: збережено {saved}, пропущено {skipped}")

    except Exception as e:
        print(f"  [помилка] {channel}: {e}")


async def main():
    # Створюємо папку для медіа якщо не існує
    os.makedirs(MEDIA_DIR, exist_ok=True)

    # Ініціалізуємо БД (якщо ще не зроблено)
    init_db()

    print("Підключення до Telegram...")
    async with TelegramClient(SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        print("Підключено.\n")
        for channel in SOURCE_CHANNELS:
            await fetch_from_channel(client, channel)

    print(f"\n{'═' * 50}")
    print("Парсинг завершено.")


if __name__ == "__main__":
    asyncio.run(main())
