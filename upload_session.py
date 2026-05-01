"""
Конвертація Telethon-сесії у рядок для Render.

Як використовувати:
    python upload_session.py

Скрипт читає reposter_session.session, копіює auth-дані у StringSession
і виводить SESSION_STRING — рядок для Environment Variable на Render.

Після цього parser/fetch.py автоматично використовує SESSION_STRING
замість файлу сесії.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID   = os.getenv("TELEGRAM_API_ID", "")
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

# Абсолютний шлях до кореня проєкту (де лежить .session файл)
ROOT_DIR     = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(ROOT_DIR, "reposter_session")


async def main():
    if not API_ID or not API_HASH:
        print("❌ Помилка: TELEGRAM_API_ID або TELEGRAM_API_HASH не знайдено в .env")
        sys.exit(1)

    session_path = SESSION_FILE + ".session"
    if not os.path.isfile(session_path):
        print(f"❌ Файл сесії не знайдено: {session_path}")
        print("   Спочатку запустіть: python parser/fetch.py")
        sys.exit(1)

    print(f"Читаю сесію з: {session_path}")
    print("Підключення до Telegram...")

    async with TelegramClient(SESSION_FILE, int(API_ID), API_HASH) as client:
        # client.session — це SQLiteSession; save() на ній повертає None.
        # Копіюємо DC + auth_key у StringSession і викликаємо save() на ній.
        ss = StringSession()
        ss.set_dc(
            client.session.dc_id,
            client.session.server_address,
            client.session.port,
        )
        ss.auth_key = client.session.auth_key
        session_string = ss.save()

    if not session_string:
        print("❌ Не вдалося отримати SESSION_STRING — сесія порожня або не авторизована.")
        print("   Переконайтесь, що reposter_session.session є валідною авторизованою сесією.")
        sys.exit(1)

    print()
    print("=" * 60)
    print("SESSION_STRING (скопіюйте це значення на Render):")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print()
    print("Інструкція для Render:")
    print("  1. Відкрийте ваш сервіс на render.com")
    print("  2. Environment → Add Environment Variable")
    print("  3. Key:   SESSION_STRING")
    print("  4. Value: (вставте рядок вище)")
    print("  5. Save Changes → Manual Deploy")


if __name__ == "__main__":
    asyncio.run(main())
