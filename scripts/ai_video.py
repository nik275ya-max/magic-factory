"""
Magic Factory — Генератор ИИ-видео
Создаёт сцены-клипы через Polza Media API (текст → видео).
Бюджетная модель по умолчанию: grok-imagine-video-1-5 (~1.62 руб/сек @480p).
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
import yaml

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

API_URL = "https://polza.ai/api/v1/media"


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_scene_prompts(script: dict, scenes_count: int) -> list[str]:
    """Строит промпты для сцен из данных скрипта."""
    title = script.get("title", "magic trick")
    category = script.get("category", "card magic")
    keywords = script.get("keywords", ["magic", "cards", "illusionist"])
    hook = script.get("hook", "")

    style = (
        "Vertical 9:16 magic trick video, cinematic lighting, dark stage background, "
        "shallow depth of field, film grain, high detail, smooth camera push-in, "
        "professional magician performance, no text"
    )

    scenes = []

    # Сцена 0 — хук: руки мага крупным планом
    hook_scene = (
        f"Extreme close-up of a magician's hands performing {category}, "
        "flourishing playing cards with quick finger movements, dramatic rim lighting, "
        + style
    )
    scenes.append(hook_scene)

    # Средние сцены — по ключевым словам
    middle_count = scenes_count - 2
    for i in range(max(middle_count, 1)):
        kw = keywords[i % len(keywords)]
        scene = (
            f"Magician on stage performing {kw}, mysterious atmosphere, "
            "audience watching in amazement, amber spotlight, "
            + style
        )
        scenes.append(scene)

    # Финальная сцена — reveal/аплодисменты
    finale = (
        f"Finale of {category} trick, audience applauding, magician bowing, "
        "confetti and stage lights, triumphant mood, "
        + style
    )
    scenes.append(finale)

    return scenes[:scenes_count]


def request_clip(api_key: str, model: str, prompt: str, cfg: dict) -> str:
    """Отправляет запрос на генерацию одного клипа, возвращает id генерации."""
    input_payload = {
        "prompt": prompt,
        "aspect_ratio": cfg["aspect_ratio"],
        "resolution": cfg["resolution"],
        "duration": str(int(cfg["clip_duration"])),
    }

    if "seedance" in model.lower() and not cfg.get("generate_audio"):
        input_payload["generate_audio"] = "false"

    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": input_payload, "async": True},
        timeout=60,
    )

    if resp.status_code >= 400:
        print(f"      [!] Ошибка запроса ({resp.status_code}): {resp.text[:300]}")
        return ""

    data = resp.json()
    return data.get("id", "")


def poll_clip(api_key: str, gen_id: str, interval: int = 10, max_wait: int = 600) -> str | None:
    """Ждёт завершения генерации, возвращает URL результата."""
    url = f"{API_URL}/{gen_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0

    while elapsed < max_wait:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            data = resp.json()

            status = data.get("status", "processing")

            if status == "completed":
                result = data.get("data", {})
                if isinstance(result, dict):
                    return result.get("url")
                elif isinstance(result, list) and result:
                    return result[0].get("url")
                return None
            elif status == "failed":
                print(f"      [!] Генерация не удалась: {data.get('error')}")
                return None
            elif status == "cancelled":
                print("      [!] Генерация отменена")
                return None
        except Exception as e:
            print(f"      [!] Ошибка при опросе: {e}")

        time.sleep(interval)
        elapsed += interval

    print(f"      [!] Таймаут ожидания ({max_wait}с) для {gen_id}")
    return None


def download_file(url: str, output_path: Path) -> bool:
    """Скачивает сгенерированный клип."""
    try:
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"      [!] Ошибка скачивания: {e}")
        return False


def process_script(script_path: Path, config: dict, ai_dir: Path) -> dict:
    """Генерирует клипы для одного скрипта."""
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    script_id = script["id"][:8]
    ai_cfg = config["ai_video"]
    api_key = config["polza"]["api_key"]

    output_dir = ai_dir / script_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Проверяем: может клипы уже сгенерированы
    existing = sorted(output_dir.glob("scene_*.mp4"))
    if existing:
        print(f"    [AI] {script_id} — уже есть {len(existing)} клипов, пропускаю")
        return {"script_id": script_id, "clips_downloaded": len(existing), "cost_rub_est": 0}

    print(f"    [AI] {script_id} — {script.get('title', 'без названия')}")
    print(f"        модель: {ai_cfg['model']} | {ai_cfg['resolution']} | {ai_cfg['aspect_ratio']}")

    prompts = build_scene_prompts(script, int(ai_cfg["scenes_per_video"]))

    # Шаг 1: раздаём все сцены на генерацию (параллельно на стороне провайдера)
    tasks = []
    for i, prompt in enumerate(prompts):
        gen_id = request_clip(api_key, ai_cfg["model"], prompt, ai_cfg)
        if gen_id:
            tasks.append((i, gen_id))
            print(f"        сцена {i + 1}/{len(prompts)} -> {gen_id}")
        else:
            print(f"        сцена {i + 1}/{len(prompts)} — не отправлена")

    if not tasks:
        print("    [!] Не удалось отправить ни одной сцены")
        return {"script_id": script_id, "clips_downloaded": 0, "cost_rub_est": 0}

    # Шаг 2: ждём завершения всех генераций (последовательно по каждой)
    downloaded = 0
    total_cost = 0.0
    clip_duration = float(ai_cfg["clip_duration"]) / 1.0
    price = float(ai_cfg.get("price_per_second", 1.62))

    for i, gen_id in tasks:
        print(f"        ожидание сцены {i + 1}/{len(tasks)}...")
        url = poll_clip(api_key, gen_id)
        if not url:
            continue

        filename = f"scene_{i:02d}_ai.mp4"
        filepath = output_dir / filename

        print(f"        скачиваю: {filename}")
        if download_file(url, filepath):
            downloaded += 1
            total_cost += clip_duration * price

    # Сохраняем метаданные
    result = {
        "script_id": script_id,
        "model": ai_cfg["model"],
        "resolution": ai_cfg["resolution"],
        "clips_downloaded": downloaded,
        "clips": [f"scene_{i:02d}_ai.mp4" for i in range(downloaded)],
        "cost_rub_est": round(total_cost, 2),
    }

    with open(output_dir / "_ai_info.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"        итог: {downloaded} клипов, ~{total_cost:.2f} руб")
    return result


def main():
    config = load_config()

    ai_cfg = config.get("ai_video")
    if not ai_cfg or not ai_cfg.get("enabled"):
        print("[!] ИИ-видео выключено в config.yaml (ai_video.enabled: false)")
        print("    В пайплайне включится автоматически. Запуск вручную:")
        print("    python scripts/ai_video.py --force")
        return

    api_key = config["polza"]["api_key"]
    if not api_key or api_key == "YOUR-POLZA-KEY-HERE":
        print("[!] Укажи polza.api_key в config.yaml")
        return

    model = ai_cfg.get("model", "grok-imagine-video-1-5")
    price = float(ai_cfg.get("price_per_second", 1.62))
    est = int(ai_cfg["clip_duration"]) * int(ai_cfg["scenes_per_video"]) * price
    print(f"[*] Генерация ИИ-видео")
    print(f"    Модель: {model} | {ai_cfg.get('resolution')} | {ai_cfg.get('aspect_ratio')}")
    print(f"    Ориентир: ~{est:.1f} руб за видео ({price} руб/сек)")

    scripts_dir = Path(__file__).parent.parent / "data" / "scripts"
    ai_dir = Path(__file__).parent.parent / "data" / "ai_video"
    ai_dir.mkdir(parents=True, exist_ok=True)

    # Собираем скрипты
    force = "--force" in sys.argv
    if not force and len(sys.argv) > 1 and sys.argv[1] not in ("--all", "--force"):
        script_files = [scripts_dir / sys.argv[1]]
    else:
        script_files = sorted(scripts_dir.glob("*.json"))
        script_files = [f for f in script_files if not f.name.startswith("_")]

    if not script_files:
        print("[!] Не найдено скриптов в data/scripts/")
        return

    print(f"[*] Обрабатываю {len(script_files)} скриптов...")

    total_cost = 0.0
    success = 0
    for script_file in script_files:
        try:
            result = process_script(script_file, config, ai_dir)
            if result["clips_downloaded"] > 0:
                success += 1
            total_cost += result.get("cost_rub_est", 0)
        except Exception as e:
            print(f"    [!] Ошибка {script_file.name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n[+] Готово: {success}/{len(script_files)} скриптов с ИИ-клипами")
    print(f"    Оценочная стоимость: ~{total_cost:.2f} руб")
    print(f"    Реальные расходы смотри: https://polza.ai/dashboard/usage")


if __name__ == "__main__":
    main()