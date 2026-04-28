# 🧠 ЕмоАтлас Репостер

Автоматичний сервіс для збору, переписування і публікації психологічних постів у Telegram канал за допомогою Claude AI.

## ✨ Можливості

- 📥 Парсинг постів з Telegram каналів-джерел
- 🤖 Переписування текстів під стиль вашого каналу через Claude AI
- 📊 Автоматична генерація опитувань для кожного посту
- 🖼️ Підтримка фото і відео
- 🌐 Зручний веб-інтерфейс з темною темою
- ✏️ Редактор постів перед публікацією

## 🚀 Встановлення

### 1. Клонуйте репозиторій
```bash
git clone https://github.com/YOUR_USERNAME/emo-atlas-reposter.git
cd emo-atlas-reposter
```

### 2. Встановіть залежності
```bash
pip install telethon anthropic python-telegram-bot flask
```

### 3. Створіть файл .env
Скопіюйте `.env.example` і заповніть своїми даними:
```bash
cp .env.example .env
```

### 4. Налаштуйте config.py
Вкажіть свій Telegram канал і канали-джерела.

### 5. Запустіть
Двічі клікніть на `start.bat` або:
```bash
python -m web.app
```
Відкрийте браузер: http://localhost:5000

## ⚙️ Налаштування

Відредагуйте `config.py`:
```python
CHANNEL_ID = "@your_channel"  # Ваш канал
SOURCE_CHANNELS = [
    "@channel1",
    "@channel2",
]
```

## 🔑 Необхідні API ключі

| Ключ | Де отримати |
|------|-------------|
| `TELEGRAM_API_ID` і `TELEGRAM_API_HASH` | https://my.telegram.org |
| `BOT_TOKEN` | @BotFather в Telegram |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |

## 📁 Структура проєкту

```
reposter/
├── ai/
│   └── rewrite.py          # Переписування через Claude AI
├── bot/
│   └── publish.py          # Публікація в Telegram
├── db/
│   ├── database.py         # Підключення до SQLite
│   └── posts.db            # База даних постів
├── media/                  # Завантажені фото і відео
├── parser/
│   └── fetch.py            # Парсинг каналів через Telethon
├── web/
│   ├── app.py              # Flask веб-панель
│   └── templates/          # HTML шаблони
├── config.py               # Налаштування проєкту
├── start.bat               # Швидкий запуск (Windows)
└── README.md
```

## 🛡️ Безпека

- Ніколи не публікуйте файл `.env` з вашими ключами
- Файл `reposter_session.session` також приватний

## 📄 Ліцензія

MIT License — використовуйте вільно як основу для своїх проєктів.
