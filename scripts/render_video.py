"""
Magic Factory — Сборщик видео
Склеивает стоковые клипы, озвучку, текстовые оверлеи и музыку в финальный MP4.
Использует FFmpeg напрямую через subprocess.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import yaml


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_audio_duration(audio_path: str) -> float:
    """Получает длительность аудиофайла через ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def get_video_duration(video_path: str) -> float:
    """Получает длительность видеофайла."""
    return get_audio_duration(video_path)


def find_stock_clips(script_id: str, stock_dir: Path) -> list[Path]:
    """Находит скачанные стоковые клипы для скрипта."""
    script_stock = stock_dir / script_id
    if not script_stock.exists():
        return []
    clips = sorted(script_stock.glob("stock_*.mp4"))
    return clips


def find_music(music_dir: Path) -> Path | None:
    """Находит фоновую музыку."""
    for ext in ["*.mp3", "*.wav", "*.ogg", "*.m4a"]:
        files = list(music_dir.glob(ext))
        if files:
            return files[0]
    return None


def create_text_overlay_filter(overlays: list, config: dict) -> str:
    """Создаёт FFmpeg filter для текстовых оверлеев."""
    if not overlays:
        return ""

    video_cfg = config["video"]["text"]
    font_size = video_cfg["font_size"]
    font_color = video_cfg["font_color"]
    stroke_color = video_cfg["stroke_color"]
    stroke_width = video_cfg["stroke_width"]

    filters = []
    for i, overlay in enumerate(overlays):
        time_sec = overlay.get("time_sec", 0)
        text = overlay.get("text", "").replace("'", "'\\''").replace(":", "\\:")
        style = overlay.get("style", "info")

        # Разные стили для разных типов
        if style == "hook":
            fs = int(font_size * 1.3)
            y_pos = "h/2-th/2"
        else:
            fs = font_size
            y_pos = "h*0.75-th"

        drawtext = (
            f"drawtext=text='{text}'"
            f":fontsize={fs}"
            f":fontcolor={font_color}"
            f":borderw={stroke_width}"
            f":bordercolor={stroke_color}"
            f":x=(w-tw)/2"
            f":y={y_pos}"
            f":enable='between(t,{time_sec},{time_sec + 5})'"
        )
        filters.append(drawtext)

    return ",".join(filters)


def render_video(script: dict, config: dict, data_dir: Path, output_dir: Path) -> str | None:
    """Собирает финальное видео для одного скрипта."""
    script_id = script["id"][:8]
    audio_dir = data_dir / "audio"
    stock_dir = data_dir / "stock"

    # Пути
    audio_path = audio_dir / f"{script_id}.mp3"
    if not audio_path.exists():
        print(f"    [!] Нет аудио для {script_id}, пропускаю")
        return None

    # Длительность аудио = цельная длительность видео
    audio_duration = get_audio_duration(str(audio_path))

    # Стоковые клипы
    clips = find_stock_clips(script_id, stock_dir)
    if not clips:
        print(f"    [!] Нет стоковых клипов для {script_id}, пропускаю")
        return None

    print(f"    [RENDER] {script_id} — аудио: {audio_duration:.1f}с, клипов: {len(clips)}")

    w = config["video"]["width"]
    h = config["video"]["height"]
    fps = config["video"]["fps"]

    # Формируем FFmpeg команду
    with tempfile.TemporaryDirectory() as tmp:

        # 1. Ресайчим все клипы под один размер и fps
        resized_clips = []
        for i, clip in enumerate(clips):
            resized = os.path.join(tmp, f"clip_{i:02d}.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-i", str(clip),
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}",
                "-an",  # убираем звук из клипов
                "-c:v", config["video"]["codec"],
                "-preset", "fast",
                "-t", "10",  # макс 10 сек на клип
                resized,
            ]
            subprocess.run(cmd, capture_output=True, check=False)
            if os.path.exists(resized):
                resized_clips.append(resized)

        if not resized_clips:
            print(f"    [!] Не удалось обработать клипы для {script_id}")
            return None

        # 2. Создаём конкат-файл для склейки клипов
        concat_file = os.path.join(tmp, "concat.txt")
        with open(concat_file, "w") as f:
            for clip in resized_clips:
                f.write(f"file '{clip}'\n")

        # Склеиваем клипы в один поток
        concat_video = os.path.join(tmp, "concat.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c:v", config["video"]["codec"],
            "-preset", "fast",
            concat_video,
        ]
        subprocess.run(cmd, capture_output=True, check=False)

        if not os.path.exists(concat_video):
            print(f"    [!] Ошибка склейки клипов для {script_id}")
            return None

        # 3. Нарезаем склеенное видео под длительность аудио + 2 сек на CTA
        target_duration = audio_duration + 2
        trimmed_video = os.path.join(tmp, "trimmed.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-i", concat_video,
            "-t", str(target_duration),
            "-stream_loop", "-1",  # зацикливаем если видео короче
            "-t", str(target_duration),
            trimmed_video,
        ]
        subprocess.run(cmd, capture_output=True, check=False)

        if not os.path.exists(trimmed_video):
            print(f"    [!] Ошибка нарезки для {script_id}")
            return None

        # 4. Добавляем текстовые оверлеи
        overlays = script.get("text_overlays", [])
        video_with_text = os.path.join(tmp, "with_text.mp4")
        vf = f"scale={w}:{h},setsar=1"

        if overlays:
            text_filter = create_text_overlay_filter(overlays, config)
            if text_filter:
                vf = f"{vf},{text_filter}"

        cmd = [
            "ffmpeg", "-y",
            "-i", trimmed_video,
            "-vf", vf,
            "-c:v", config["video"]["codec"],
            "-preset", "fast",
            video_with_text,
        ]
        subprocess.run(cmd, capture_output=True, check=False)

        if not os.path.exists(video_with_text):
            video_with_text = trimmed_video  # fallback без текста

        # 5. Накладываем аудио
        music_dir = Path(config["music"]["directory"])
        music_path = find_music(music_dir)

        final_output = str(output_dir / f"{script_id}_final.mp4")

        if music_path:
            # С аудио озвучкой + фоновая музыка (тихо)
            music_vol = config["music"]["volume"]
            cmd = [
                "ffmpeg", "-y",
                "-i", video_with_text,
                "-i", str(audio_path),
                "-i", str(music_path),
                "-filter_complex",
                f"[1:a]aformat=channel_layouts=stereo[voice];"
                f"[2:a]volume={music_vol},aformat=channel_layouts=stereo[music];"
                f"[voice][music]amix=inputs=2:duration=first[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", config["video"]["audio_codec"],
                "-shortest",
                final_output,
            ]
        else:
            # Только озвучка
            cmd = [
                "ffmpeg", "-y",
                "-i", video_with_text,
                "-i", str(audio_path),
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", config["video"]["audio_codec"],
                "-shortest",
                final_output,
            ]

        subprocess.run(cmd, capture_output=True, check=False)

        if os.path.exists(final_output):
            file_size = os.path.getsize(final_output) / (1024 * 1024)
            print(f"    [OK] {final_output} ({file_size:.1f} MB)")
            return final_output
        else:
            print(f"    [!] Ошибка финальной сборки для {script_id}")
            return None


def main():
    config = load_config()
    data_dir = Path(__file__).parent.parent / "data"
    scripts_dir = data_dir / "scripts"
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Собираем скрипты
    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        script_files = [scripts_dir / sys.argv[1]]
    else:
        script_files = sorted(scripts_dir.glob("*.json"))
        script_files = [f for f in script_files if not f.name.startswith("_")]

    if not script_files:
        print("[!] Не найдено скриптов в data/scripts/")
        return

    print(f"[*] Собираю видео для {len(script_files)} скриптов...")
    print(f"    Разрешение: {config['video']['width']}x{config['video']['height']}")

    success = 0
    for script_file in script_files:
        with open(script_file, "r", encoding="utf-8") as f:
            script = json.load(f)

        try:
            result = render_video(script, config, data_dir, output_dir)
            if result:
                success += 1
        except Exception as e:
            print(f"    [!] Ошибка {script_file.name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n[+] Готово! Собрано {success}/{len(script_files)} видео")
    print(f"    Выходная папка: {output_dir}")


if __name__ == "__main__":
    main()
