"""
Magic Factory — Мультиплатформенная публикация
Автоматическая загрузка видео в Telegram, VK, YouTube, TikTok.
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


def load_script_info(script_id: str, scripts_dir: Path) -> dict | None:
    """Загружает скрипт по ID для получения заголовка и хэштегов."""
    for f in scripts_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        with open(f, "r", encoding="utf-8") as fh:
            script = json.load(fh)
        if script["id"].startswith(script_id):
            return script
    return None


# ============================================================
# Telegram
# ============================================================

def publish_telegram(video_path: str, script: dict, config: dict) -> bool:
    """Публикует видео в Telegram канал через бота."""
    tg_cfg = config["publish"]["telegram"]
    if not tg_cfg.get("enabled"):
        print("    [TG] Отключён в config.yaml")
        return False

    bot_token = tg_cfg["bot_token"]
    channel_id = tg_cfg["channel_id"]

    if "YOUR-" in bot_token:
        print("    [TG] Укажи bot_token в config.yaml")
        return False

    # Формируем подпись
    caption = _format_caption(script, "telegram")

    # Отправляем видео
    url = f"https://api.telegram.org/bot{bot_token}/sendVideo"

    with open(video_path, "rb") as video_file:
        resp = requests.post(
            url,
            data={
                "chat_id": channel_id,
                "caption": caption,
                "parse_mode": "HTML",
            },
            files={"video": video_file},
            timeout=120,
        )

    if resp.status_code == 200:
        print(f"    [TG] OK — {channel_id}")
        return True
    else:
        print(f"    [TG] Ошибка: {resp.status_code} — {resp.text[:200]}")
        return False


# ============================================================
# VK
# ============================================================

def publish_vk(video_path: str, script: dict, config: dict) -> bool:
    """Публикует видео в VK группу."""
    vk_cfg = config["publish"]["vk"]
    if not vk_cfg.get("enabled"):
        print("    [VK] Отключён в config.yaml")
        return False

    access_token = vk_cfg["access_token"]
    group_id = vk_cfg["group_id"]

    if "YOUR-" in access_token:
        print("    [VK] Укажи access_token в config.yaml")
        return False

    caption = _format_caption(script, "vk")

    # Шаг 1: Получаем URL для загрузки видео
    upload_url_resp = requests.get(
        "https://api.vk.com/method/video.save",
        params={
            "access_token": access_token,
            "group_id": group_id,
            "name": script.get("title", "Magic Trick"),
            "description": caption,
            "wallpost": 1,
            "v": "5.199",
        },
        timeout=30,
    )

    if upload_url_resp.status_code != 200:
        print(f"    [VK] Ошибка получения URL: {upload_url_resp.status_code}")
        return False

    upload_data = upload_url_resp.json().get("response", {})
    upload_url = upload_data.get("upload_url")
    video_id = upload_data.get("video_id")
    owner_id = upload_data.get("owner_id")

    if not upload_url:
        print(f"    [VK] Нет upload_url: {upload_data}")
        return False

    # Шаг 2: Загружаем видеофайл
    with open(video_path, "rb") as video_file:
        upload_resp = requests.post(
            upload_url,
            files={"video_file": video_file},
            timeout=300,
        )

    if upload_resp.status_code == 200:
        print(f"    [VK] OK — video{owner_id}_{video_id}")
        return True
    else:
        print(f"    [VK] Ошибка загрузки: {upload_resp.status_code}")
        return False


# ============================================================
# YouTube Shorts
# ============================================================

def publish_youtube(video_path: str, script: dict, config: dict) -> bool:
    """Загружает видео как YouTube Short (через YouTube Data API v3)."""
    yt_cfg = config["publish"]["youtube"]
    if not yt_cfg.get("enabled"):
        print("    [YT] Отключён в config.yaml")
        return False

    secrets_file = yt_cfg.get("client_secrets_file", "client_secrets.json")
    if not os.path.exists(secrets_file):
        print(f"    [YT] Нет файла {secrets_file}")
        print("    [YT] Настрой OAuth: https://console.cloud.google.com")
        return False

    # YouTube API требует OAuth2 авторизации
    # Здесь заготовка — при первой запуске откроется браузер
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("    [YT] Установи: pip install google-api-python-client google-auth google-auth-oauthlib")
        return False

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    token_file = "yt_token.json"

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    youtube = build("youtube", "v3", credentials=creds)

    caption = _format_caption(script, "youtube")

    body = {
        "snippet": {
            "title": script.get("title", "Magic Trick")[:100],
            "description": caption,
            "tags": script.get("hashtags", []) + ["shorts", "фокусы", "магия"],
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    [YT] Загрузка: {int(status.progress() * 100)}%")

    print(f"    [YT] OK — https://youtube.com/shorts/{response['id']}")
    return True


# ============================================================
# TikTok
# ============================================================

def publish_tiktok(video_path: str, script: dict, config: dict) -> bool:
    """Публикует видео в TikTok (через Content Posting API)."""
    tt_cfg = config["publish"]["tiktok"]
    if not tt_cfg.get("enabled"):
        print("    [TT] Отключён в config.yaml")
        return False

    # TikTok API требует одобрения приложения
    # Заготовка для будущей интеграции
    print("    [TT] TikTok API требует одобрения заявки")
    print("    [TT] Подать заявку: https://developers.tiktok.com/")
    return False


# ============================================================
# Helpers
# ============================================================

def _format_caption(script: dict, platform: str) -> str:
    """Форматирует подпись под платформу."""
    title = script.get("title", "")
    hashtags = script.get("hashtags", [])
    cta = script.get("cta", "")

    if platform == "telegram":
        lines = [f"<b>{title}</b>", "", cta]
        if hashtags:
            lines.append("")
            lines.append(" ".join(hashtags[:5]))
        return "\n".join(lines)

    elif platform == "vk":
        lines = [title, "", cta]
        if hashtags:
            lines.append("")
            lines.append(" ".join(hashtags[:5]))
        return "\n".join(lines)

    elif platform == "youtube":
        lines = [title, "", cta]
        if hashtags:
            lines.append("")
            lines.append(" ".join(hashtags[:8]))
        return "\n".join(lines)

    elif platform == "tiktok":
        lines = [cta]
        if hashtags:
            lines.append(" ".join(hashtags[:5]))
        return "\n".join(lines)

    return f"{title}\n\n{cta}"


def main():
    config = load_config()
    output_dir = Path(__file__).parent.parent / "output"
    scripts_dir = Path(__file__).parent.parent / "data" / "scripts"

    # Определяем видео для публикации
    if len(sys.argv) > 1:
        # Конкретное видео
        video_files = [output_dir / sys.argv[1]]
    else:
        video_files = sorted(output_dir.glob("*_final.mp4"))

    if not video_files:
        print("[!] Нет видео для публикации в output/")
        return

    # Определяем платформы
    platforms = []
    for arg in sys.argv[2:]:
        if arg in ("telegram", "vk", "youtube", "tiktok", "all"):
            platforms.append(arg)

    if not platforms:
        platforms = ["telegram", "vk"]

    print(f"[*] Публикую {len(video_files)} видео в: {', '.join(platforms)}")

    publish_delay = config["pipeline"].get("publish_delay", 300)

    results = {"success": 0, "failed": 0, "skipped": 0}

    for i, video_file in enumerate(video_files):
        # Извлекаем script_id из имени файла
        script_id = video_file.name.split("_")[0]
        script = load_script_info(script_id, scripts_dir)

        if not script:
            print(f"  [{i+1}] {video_file.name} — нет данных скрипта, пропускаю")
            results["skipped"] += 1
            continue

        print(f"\n  [{i+1}/{len(video_files)}] {script.get('title', video_file.name)}")

        video_success = False
        for platform in platforms:
            if platform == "all":
                continue

            publisher = {
                "telegram": publish_telegram,
                "vk": publish_vk,
                "youtube": publish_youtube,
                "tiktok": publish_tiktok,
            }.get(platform)

            if publisher:
                try:
                    if publisher(str(video_file), script, config):
                        video_success = True
                except Exception as e:
                    print(f"    [{platform.upper()}] Ошибка: {e}")

        if video_success:
            results["success"] += 1
        else:
            results["failed"] += 1

        # Задержка между видео (чтобы не спамить)
        if i < len(video_files) - 1:
            print(f"    Пауза {publish_delay}с перед следующим видео...")
            time.sleep(publish_delay)

    print(f"\n[+] Результаты публикации:")
    print(f"    Успешно: {results['success']}")
    print(f"    Ошибки: {results['failed']}")
    print(f"    Пропущено: {results['skipped']}")


if __name__ == "__main__":
    main()
