"""
Magic Factory — Генератор скриптов
LLM пакетно генерирует JSON-скрипты для видео про фокусы.
"""

import json
import os
import sys
import uuid
import yaml
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import openai


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


SCRIPT_SYSTEM_PROMPT = """Ты — создатель коротких видео про фокусы и магию для TikTok/YouTube Shorts.
Генерируй увлекательные скрипты на русском языке.

Структура видео (30-40 секунд):
1. ХУК (0-3 сек) — цепляющая фраза, которая не даёт листнуть
2. ЗАСТАВКА (3-6 сек) — контекст, интересный факт
3. ОСНОВНАЯ ЧАСТЬ (6-28 сек) — рассказ о фокусе, его истории, как работает
4. ФИНАЛ (28-35 сек) — неожиданный поворот или CTA

Стиль: как будто рассказываешь другу. Без воды. Каждое слово должно держать внимание.

ВАЖНО: Отвечай ТОЛЬКО валидным JSON без markdown-обёрток."""

SCRIPT_USER_PROMPT_TEMPLATE = """Сгенерируй {count} уникальных скриптов на тему фокусов.

Доступные категории ( чередуй):
- карточные фокусы
- фокусы с монетами
- фокусы с верёвкой
- ментальные фокусы / чтение мыслей
- фокусы с бумагой
- фокусы с бутылкой/стаканом
- рекордные фокусы
- история известных фокусов
- фокусы Дэвид Копперфильд / Хаунни
- фокусы которые можно повторить дома

Верни JSON-массив:
[
  {{
    "id": "уникальный_id",
    "category": "категория",
    "title": "короткий заголовок для видео",
    "hook": "цепляющая первая фраза (0-3 сек)",
    "body": "основной текст озвучки (весь текст целиком)",
    "cta": "призыв к действию в конце",
    "keywords": ["ключевое_слово1", "ключевое_слово2", "ключевое_слово3", "ключевое_слово4", "ключевое_слово5"],
    "text_overlays": [
      {{"time_sec": 0, "text": "ТЕКСТ НА ЭКРАНЕ", "style": "hook"}},
      {{"time_sec": 15, "text": "ДРУГОЙ ТЕКСТ", "style": "info"}}
    ],
    "hashtags": ["#фокусы", "#магия", "#иллюзии"]
  }}
]

Все поля обязательны. Текст озвучки должен быть 250-350 слов (30-40 сек при средней скорости речи).
Keywords — на английском, для поиска стокового видео.
text_overlays — ключевые фразы, которые появятся на экране.
Поле id должно быть уникальным UUID-4."""


def generate_scripts(config: dict, count: int = 10) -> list[dict]:
    """Генерирует пачку скриптов через LLM."""
    client = openai.OpenAI(
        api_key=config["polza"]["api_key"],
        base_url=config["polza"]["base_url"],
    )

    prompt = SCRIPT_USER_PROMPT_TEMPLATE.format(count=count)

    print(f"[*] Генерирую {count} скриптов через {config['polza']['model']}...")

    response = client.chat.completions.create(
        model=config["polza"]["model"],
        messages=[
            {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=config["polza"].get("temperature", 0.9),
        max_tokens=config["polza"].get("max_tokens", 8000),
    )

    raw = response.choices[0].message.content.strip()

    # Убираем markdown-обёртку если LLM её добавил
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])

    scripts = json.loads(raw)

    # Валидация и нормализация
    for script in scripts:
        if "id" not in script:
            script["id"] = str(uuid.uuid4())
        script["generated_at"] = datetime.now().isoformat()
        script["status"] = "new"

    print(f"[+] Сгенерировано {len(scripts)} скриптов")
    return scripts


def save_scripts(scripts: list[dict], output_dir: Path):
    """Сохраняет каждый скрипт в отдельный JSON-файл."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for script in scripts:
        filename = f"{script['id'][:8]}.json"
        filepath = output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        print(f"    -> {filename} ({script.get('title', 'без названия')})")


def generate_topics_only(config: dict, count: int = 50) -> list[str]:
    """Генерирует список тем для скриптов (без полного текста)."""
    client = openai.OpenAI(
        api_key=config["polza"]["api_key"],
        base_url=config["polza"]["base_url"],
    )

    response = client.chat.completions.create(
        model=config["polza"]["model"],
        messages=[
            {
                "role": "system",
                "content": "Ты создатель контента. Генерируй темы для коротких видео про фокусы. "
                "Отвечай только JSON-массивом строк, без markdown.",
            },
            {
                "role": "user",
                "content": f"Придумай {count} цепляющих тем для видео про фокусы. "
                "Каждая тема — это готовый заголовок, который цепляет. "
                "Верни JSON-массив строк.",
            },
        ],
        temperature=1.0,
        max_tokens=3000,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])

    return json.loads(raw)


def main():
    config = load_config()
    data_dir = Path(__file__).parent.parent / "data" / "scripts"

    # Определяем количество скриптов из аргументов
    count = int(sys.argv[1]) if len(sys.argv) > 1 else config["pipeline"]["batch_size"]

    # Режим: только темы (быстро и дёшево)
    if "--topics" in sys.argv:
        topics = generate_topics_only(config, count)
        topics_path = data_dir / "_topics.json"
        with open(topics_path, "w", encoding="utf-8") as f:
            json.dump(topics, f, ensure_ascii=False, indent=2)
        print(f"[+] Сохранено {len(topics)} тем в {topics_path}")
        for i, t in enumerate(topics, 1):
            print(f"    {i}. {t}")
        return

    # Полная генерация скриптов
    scripts = generate_scripts(config, count)
    save_scripts(scripts, data_dir)

    # Сохраняем манифест
    manifest_path = data_dir / "_manifest.json"
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "count": len(scripts),
        "scripts": [
            {
                "id": s["id"],
                "title": s.get("title", ""),
                "category": s.get("category", ""),
                "filename": f"{s['id'][:8]}.json",
            }
            for s in scripts
        ],
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[+] Манифест: {manifest_path}")


if __name__ == "__main__":
    main()
