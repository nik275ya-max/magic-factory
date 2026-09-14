"""
Magic Factory — Генератор озвучки
Использует edge-tts для создания MP3 озвучки из JSON-скриптов.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import edge_tts
import yaml


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def generate_voice(text: str, output_path: Path, voice: str, rate: str, volume: str):
    """Генерирует MP3 из текста."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    await communicate.save(str(output_path))


def get_full_voice_text(script: dict) -> str:
    """Собирает полный текст озвучки из скрипта."""
    parts = []
    if script.get("hook"):
        parts.append(script["hook"])
    if script.get("body"):
        parts.append(script["body"])
    if script.get("cta"):
        parts.append(script["cta"])
    return " ".join(parts)


def process_script(script_path: Path, config: dict, output_dir: Path) -> dict:
    """Обрабатывает один JSON-скрипт: генерирует MP3 и SRT субтитры."""
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    voice_cfg = config["voice"]
    script_id = script["id"][:8]

    # Текст озвучки
    text = get_full_voice_text(script)

    # MP3
    mp3_path = output_dir / f"{script_id}.mp3"

    print(f"    [TTS] {script_id} — {script.get('title', 'без названия')}")

    asyncio.run(
        generate_voice(
            text,
            mp3_path,
            voice_cfg["voice_name"],
            voice_cfg["rate"],
            voice_cfg["volume"],
        )
    )

    # Генерируем простой SRT из текстовых оверлеев
    srt_path = output_dir / f"{script_id}.srt"
    overlays = script.get("text_overlays", [])
    if overlays:
        _write_srt(overlays, text, srt_path)

    return {
        "id": script_id,
        "mp3": str(mp3_path),
        "srt": str(srt_path) if overlays else None,
        "text_length": len(text),
    }


def _write_srt(overlays: list, full_text: str, output_path: Path):
    """Генерирует SRT-субтитры, разбивая текст по таймкодам оверлеев."""
    words = full_text.split()
    total_words = len(words)

    srt_lines = []
    for i, overlay in enumerate(overlays):
        start_time = overlay.get("time_sec", 0)
        # Конец следующего оверлея или 5 секунд после текущего
        if i + 1 < len(overlays):
            end_time = overlays[i + 1].get("time_sec", start_time + 5)
        else:
            end_time = start_time + 5

        # Разбиваем длинные тексты оверлеев на блоки по ~5 слов
        text = overlay.get("text", "")
        text_words = text.split()
        chunk_size = 5
        chunks = [text_words[j : j + chunk_size] for j in range(0, len(text_words), chunk_size)]

        chunk_duration = (end_time - start_time) / max(len(chunks), 1)

        for ci, chunk in enumerate(chunks):
            chunk_start = start_time + ci * chunk_duration
            chunk_end = chunk_start + chunk_duration
            srt_lines.append(
                f"{len(srt_lines) + 1}\n"
                f"{_format_srt_time(chunk_start)} --> {_format_srt_time(chunk_end)}\n"
                f"{' '.join(chunk)}\n"
            )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines))


def _format_srt_time(seconds: float) -> str:
    """Конвертирует секунды в формат SRT HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def main():
    config = load_config()
    scripts_dir = Path(__file__).parent.parent / "data" / "scripts"
    audio_dir = Path(__file__).parent.parent / "data" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Собираем скрипты для обработки
    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        # Конкретный файл
        script_files = [scripts_dir / sys.argv[1]]
    else:
        # Все скрипты из data/scripts/
        script_files = sorted(scripts_dir.glob("*.json"))
        script_files = [f for f in script_files if not f.name.startswith("_")]

    if not script_files:
        print("[!] Не найдено скриптов в data/scripts/")
        print("    Сначала запусти: python scripts/generate_scripts.py")
        return

    print(f"[*] Озвучиваю {len(script_files)} скриптов...")
    print(f"    Голос: {config['voice']['voice_name']}")
    print(f"    Скорость: {config['voice']['rate']}")

    results = []
    for script_file in script_files:
        try:
            result = process_script(script_file, config, audio_dir)
            results.append(result)
        except Exception as e:
            print(f"    [!] Ошибка {script_file.name}: {e}")

    # Сохраняем результаты
    results_path = audio_dir / "_voice_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[+] Готово! Озвучено {len(results)}/{len(script_files)} скриптов")
    print(f"    Результаты: {results_path}")


if __name__ == "__main__":
    main()
