"""
Magic Factory — Загрузчик стокового видео
Использует Pexels API для поиска и скачивания стоковых видео по ключевым словам.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests
import yaml


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def search_videos(
    api_key: str,
    query: str,
    per_page: int = 10,
    orientation: str = "portrait",
    min_duration: int = 5,
) -> list[dict]:
    """Ищет видео на Pexels по запросу."""
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Фильтруем по минимальной длительности
    videos = []
    for video in data.get("videos", []):
        if video.get("duration", 0) >= min_duration:
            videos.append(
                {
                    "id": video["id"],
                    "duration": video["duration"],
                    "width": video["width"],
                    "height": video["height"],
                    "url": video["url"],
                    # Берём лучшее качество (HD)
                    "video_files": video.get("video_files", []),
                }
            )

    return videos


def pick_best_file(video: dict, target_height: int = 1920) -> dict | None:
    """Выбирает лучший видеофайл по соотношению размер/качество."""
    files = video.get("video_files", [])
    if not files:
        return None

    # Фильтруем по высоте, ищем ближайшую к target_height
    portrait_files = [f for f in files if f.get("height", 0) >= f.get("width", 0)]

    if not portrait_files:
        portrait_files = files

    # Сортируем по приближению к target_height
    portrait_files.sort(key=lambda f: abs(f.get("height", 0) - target_height))

    return portrait_files[0] if portrait_files else files[0]


def download_video(url: str, output_path: Path) -> bool:
    """Скачивает видеофайл."""
    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"      [!] Ошибка скачивания: {e}")
        return False


def process_script(script_path: Path, config: dict, stock_dir: Path) -> dict:
    """Для одного скрипта — ищет и скачивает стоковые видео по keywords."""
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    script_id = script["id"][:8]
    keywords = script.get("keywords", ["magic", "cards", "illusionist"])

    api_key = config["pexels"]["api_key"]
    clips_needed = config["pexels"]["clips_per_video"]
    orientation = config["pexels"].get("orientation", "portrait")
    min_duration = config["pexels"].get("min_duration", 5)

    output_dir = stock_dir / script_id
    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    seen_ids = set()

    print(f"    [STOCK] {script_id} — {script.get('title', 'без названия')}")

    for keyword in keywords:
        if len(downloaded) >= clips_needed:
            break

        print(f"      -> поиск: '{keyword}'")

        try:
            videos = search_videos(api_key, keyword, per_page=5, orientation=orientation, min_duration=min_duration)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"      [!] Rate limit, жду 60 сек...")
                time.sleep(60)
                continue
            print(f"      [!] API ошибка: {e}")
            continue

        for video in videos:
            if len(downloaded) >= clips_needed:
                break
            if video["id"] in seen_ids:
                continue
            seen_ids.add(video["id"])

            best_file = pick_best_file(video, config["video"]["height"])
            if not best_file:
                continue

            filename = f"stock_{len(downloaded):02d}_pexels_{video['id']}.mp4"
            filepath = output_dir / filename

            print(f"      -> скачиваю: {filename} ({best_file.get('height', '?')}p)")
            if download_video(best_file["link"], filepath):
                downloaded.append(
                    {
                        "filename": filename,
                        "pexels_id": video["id"],
                        "duration": video["duration"],
                        "width": best_file.get("width"),
                        "height": best_file.get("height"),
                        "keyword": keyword,
                    }
                )

        # Пауза между запросами чтобы не словить rate limit
        time.sleep(1)

    # Сохраняем результат
    result = {
        "script_id": script_id,
        "title": script.get("title", ""),
        "clips_downloaded": len(downloaded),
        "clips": downloaded,
    }

    with open(output_dir / "_stock_info.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def main():
    config = load_config()
    scripts_dir = Path(__file__).parent.parent / "data" / "scripts"
    stock_dir = Path(__file__).parent.parent / "data" / "stock"

    if not config["pexels"]["api_key"] or config["pexels"]["api_key"] == "YOUR-PEXELS-KEY-HERE":
        print("[!] Укажи Pexels API ключ в config.yaml")
        print("    Получи бесплатно: https://www.pexels.com/api/")
        return

    # Собираем скрипты
    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        script_files = [scripts_dir / sys.argv[1]]
    else:
        script_files = sorted(scripts_dir.glob("*.json"))
        script_files = [f for f in script_files if not f.name.startswith("_")]

    if not script_files:
        print("[!] Не найдено скриптов в data/scripts/")
        return

    print(f"[*] Скачиваю стоковые видео для {len(script_files)} скриптов...")

    total_clips = 0
    for script_file in script_files:
        try:
            result = process_script(script_file, config, stock_dir)
            total_clips += result["clips_downloaded"]
        except Exception as e:
            print(f"    [!] Ошибка {script_file.name}: {e}")

    print(f"\n[+] Готово! Скачано {total_clips} клипов для {len(script_files)} скриптов")


if __name__ == "__main__":
    main()
