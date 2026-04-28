"""
Модуль для переписування постів під стиль каналу "Емоційний атлас".

Логіка:
1. Беремо всі пости зі статусом 'новий' з бази даних.
2. Перевіряємо текст на рекламні ознаки — якщо знайдено, ставимо статус 'реклама'.
3. Кожен не-рекламний текст відправляємо до Anthropic API (Claude).
4. Промпт повертає визначену емоцію + перероблений текст у структурованому форматі.
5. Зберігаємо результат у поле rewritten_text, оновлюємо статус на 'переписаний'.
6. Виводимо оригінал і результат у термінал під час обробки.
7. Після завершення показуємо перші 3 переписані пости для порівняння.
"""

import re
import anthropic
from db.database import get_connection
from config import ANTHROPIC_API_KEY

# ─── Фільтр реклами ───────────────────────────────────────────────────────────

# Слова, які вказують на рекламний характер посту
AD_KEYWORDS = [
    "підписуйся", "купи", "замов", "знижка", "акція", "промокод",
    "реклама", "партнер", "співпраця", "розіграш", "безкоштовно отримай",
]

# Комерційні емодзі
AD_EMOJI = set("💰💳🛒💵💴💶💷🏷💲🤑")

# Посилання на сторонні Telegram-канали / боти
AD_LINK_PATTERN = re.compile(r"t\.me/[^\s\)\"']+", re.IGNORECASE)


def is_ad(text: str) -> tuple[bool, str]:
    """
    Повертає (True, причина) якщо текст схожий на рекламу, інакше (False, '').
    Перевіряє три ознаки: ключові слова, комерційні емодзі, посилання t.me/.
    """
    lower = text.lower()

    for kw in AD_KEYWORDS:
        if kw in lower:
            return True, f"ключове слово «{kw}»"

    found_emoji = AD_EMOJI & set(text)
    if found_emoji:
        return True, f"комерційне емодзі {''.join(found_emoji)}"

    links = AD_LINK_PATTERN.findall(text)
    if links:
        return True, f"посилання {links[0]}"

    return False, ""

# ─── Промпт ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ти — редактор каналу "Емоційний атлас".
Стиль каналу: теплий, науково обґрунтований, без кліше та маніпуляцій,
з повагою до читача. Тексти спираються на психологію, але написані живою мовою.
Ти ніколи не використовуєш банальні фрази на зразок "це нормально" або "бережи себе".
Завжди пишеш від серця, але з опорою на факти."""

USER_PROMPT_TEMPLATE = """Ось оригінальний пост з іншого каналу:

---
{text}
---

Виконай чотири кроки:
1. Визнач переважаючу емоцію в тексті (тривога, смуток, радість, злість, сором тощо).
2. Посили цю емоцію — зроби її більш відчутною і конкретною.
3. Перепиши текст під стиль каналу "Емоційний атлас":
   - 3–5 речень
   - тепло, але без кліше
   - науково обґрунтовано, але доступно
   - одне запитання до читача в самому кінці
4. Склади анонімне опитування для Telegram пов'язане з цією емоцією:
   - питання має допомогти читачу усвідомити свій власний емоційний стан
   - рівно 4 варіанти відповіді — конкретні, без кліше, різні за інтенсивністю
   - жоден варіант не повинен бути "правильним" або кращим за інші

Поверни відповідь ТІЛЬКИ у такому форматі (без зайвих слів навколо):
ЕМОЦІЯ: <назва емоції одним словом>
ТЕКСТ: <готовий пост>
ПИТАННЯ: <питання для опитування>
ВАРІАНТ1: <перший варіант>
ВАРІАНТ2: <другий варіант>
ВАРІАНТ3: <третій варіант>
ВАРІАНТ4: <четвертий варіант>"""

# ─── Claude API ───────────────────────────────────────────────────────────────

def rewrite_text(original_text: str) -> dict:
    """
    Відправляє текст до Claude.
    Повертає словник {"emotion": str, "text": str}.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(text=original_text),
            }
        ],
    )
    raw = message.content[0].text.strip()
    return _parse_response(raw)


def _parse_response(raw: str) -> dict:
    """
    Розбирає відповідь Claude формату:
        ЕМОЦІЯ: тривога
        ТЕКСТ: ...текст...
        ПИТАННЯ: ...питання...
        ВАРІАНТ1: ...
        ВАРІАНТ2: ...
        ВАРІАНТ3: ...
        ВАРІАНТ4: ...

    Повертає словник:
        {
          "emotion":       str,
          "text":          str,
          "poll_question": str | None,
          "poll_options":  list[str] | None,   # рівно 4 варіанти
        }

    ТЕКСТ: може бути багаторядковим — парсимо його до першого рядка
    що починається з нового ключового слова (ПИТАННЯ:, ВАРІАНТN:).
    При невдалому парсингу poll_question і poll_options залишаються None.
    """
    emotion = "невідома"
    text = raw
    poll_question = None
    poll_options = None

    emotion_match  = re.search(r"ЕМОЦІЯ:\s*(.+)", raw)
    # ТЕКСТ: завершується перед першим рядком-ключем або кінцем рядка
    text_match     = re.search(r"ТЕКСТ:\s*([\s\S]+?)(?=\n[^\n]+:|\Z)", raw)
    question_match = re.search(r"ПИТАННЯ:\s*(.+)", raw)
    option_matches = [re.search(rf"ВАРІАНТ{i}:\s*(.+)", raw) for i in range(1, 5)]

    if emotion_match:
        emotion = emotion_match.group(1).strip()
    if text_match:
        text = text_match.group(1).strip()
    if question_match:
        poll_question = question_match.group(1).strip()
    if all(option_matches):
        poll_options = [m.group(1).strip() for m in option_matches]

    return {
        "emotion":       emotion,
        "text":          text,
        "poll_question": poll_question,
        "poll_options":  poll_options,
    }

# ─── База даних ───────────────────────────────────────────────────────────────

def fetch_new_posts() -> list[dict]:
    """Повертає всі пости зі статусом 'новий'."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, channel, original_text FROM posts WHERE status = 'новий'"
        ).fetchall()
    return [{"id": row[0], "channel": row[1], "original_text": row[2]} for row in rows]


def save_rewritten(post_id: int, rewritten_text: str,
                   poll_question: str | None = None,
                   poll_options: list[str] | None = None) -> None:
    """
    Зберігає перероблений текст і оновлює статус на 'переписаний'.

    poll_options зберігається як рядок через роздільник ||| —
    простий формат без залежностей, легко розбивається назад:
        options_list = poll_options_str.split("|||")
    """
    options_str = "|||".join(poll_options) if poll_options else None
    with get_connection() as conn:
        conn.execute(
            """UPDATE posts
               SET rewritten_text = ?,
                   poll_question   = ?,
                   poll_options    = ?,
                   status          = 'переписаний'
               WHERE id = ?""",
            (rewritten_text, poll_question, options_str, post_id),
        )
        conn.commit()


def mark_as_ad(post_id: int) -> None:
    """Позначає пост як рекламний — без переписування."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE posts SET status = 'реклама' WHERE id = ?",
            (post_id,),
        )
        conn.commit()

# ─── Відображення результатів ─────────────────────────────────────────────────

def print_review(results: list[dict], count: int = 3) -> None:
    """
    Виводить перші `count` успішно переписаних постів для порівняння.
    Кожен елемент results: {"original": str, "rewritten": str, "emotion": str}.
    """
    sample = results[:count]
    if not sample:
        return

    print(f"\n{'═' * 60}")
    print(f"  ПІДСУМОК: перші {len(sample)} переписані пости")
    print(f"{'═' * 60}\n")

    for i, r in enumerate(sample, start=1):
        print(f"── Пост {i} ─────────────────────────────────────────────")
        print(f"🎭 Емоція:    {r['emotion']}")
        print(f"\n📄 Оригінал:\n{r['original']}")
        print(f"\n✏️  Переписано:\n{r['rewritten']}")
        if r.get("poll_question"):
            print(f"\n📊 Опитування: {r['poll_question']}")
            for j, opt in enumerate(r.get("poll_options") or [], start=1):
                print(f"   {j}. {opt}")
        print()

# ─── Головна функція ──────────────────────────────────────────────────────────

def run_rewriter() -> None:
    """
    Основний цикл:
    - фільтрує рекламу
    - переписує решту через Claude
    - показує підсумок перших 3 результатів
    """
    posts = fetch_new_posts()

    if not posts:
        print("Немає нових постів для переписування.")
        return

    print(f"Знайдено {len(posts)} нових постів. Починаємо обробку...\n")

    rewritten_results: list[dict] = []  # для фінального перегляду
    stats = {"rewritten": 0, "ad": 0, "skipped": 0, "error": 0}

    for i, post in enumerate(posts, start=1):
        text = post["original_text"] or ""
        print(f"{'─' * 60}")
        print(f"[{i}/{len(posts)}] Канал: {post['channel']}  |  ID: {post['id']}")

        # 1. Порожній текст (пост тільки з медіа)
        if not text.strip():
            print("⚠️  Текст порожній — пропускаємо.")
            save_rewritten(post["id"], "")
            stats["skipped"] += 1
            continue

        # 2. Перевірка на рекламу
        ad, reason = is_ad(text)
        if ad:
            print(f"🚫 Реклама ({reason}) — пропускаємо.")
            mark_as_ad(post["id"])
            stats["ad"] += 1
            continue

        # 3. Переписування через Claude
        print(f"📄 Оригінал: {text[:80]}{'…' if len(text) > 80 else ''}")
        try:
            result = rewrite_text(text)
            save_rewritten(
                post["id"],
                result["text"],
                result.get("poll_question"),
                result.get("poll_options"),
            )
            print(f"🎭 Емоція:   {result['emotion']}")
            print(f"✏️  Готово:   {result['text'][:80]}{'…' if len(result['text']) > 80 else ''}")
            if result.get("poll_question"):
                print(f"📊 Питання: {result['poll_question']}")
            print()
            rewritten_results.append({
                "original": text,
                "rewritten": result["text"],
                "emotion": result["emotion"],
                "poll_question": result.get("poll_question"),
                "poll_options":  result.get("poll_options"),
            })
            stats["rewritten"] += 1
        except Exception as e:
            print(f"❌ Помилка: {e}\n")
            stats["error"] += 1

    # Підсумкова статистика
    print(f"{'─' * 60}")
    print(
        f"Готово. Переписано: {stats['rewritten']} | "
        f"Реклама: {stats['ad']} | "
        f"Порожніх: {stats['skipped']} | "
        f"Помилок: {stats['error']}"
    )

    # Перегляд перших 3 результатів
    print_review(rewritten_results)


if __name__ == "__main__":
    run_rewriter()
