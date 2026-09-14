# Magic Factory

Контент-завод коротких видео про фокусы и магию (9:16, 30-40 сек) для TikTok, YouTube Shorts, Telegram и VK.

Полная автоматизация пайплайна: скрипты → озвучка → стоковые/ИИ-клипы → сборка → публикация.

## Возможности

- **Скрипты** — генерация через Polza.AI (API агрегатор 400+ LLM моделей, оплата в рублях)
- **Озвучка** — бесплатный TTS `edge-tts` (Microsoft Neural голоса, рус/англ)
- **Сток** — вертикальные видео с Pexels по ключевым словам из скрипта (бесплатно)
- **ИИ-видео** — генерация сцен текстом через Polza Media API (от ~1.6 ₽/сек)
- **Сборка** — склейка клипов + текст оверлеи + фоновая музыка через FFmpeg
- **Публикация** — автопостинг в Telegram (Bot API) и VK, OAuth-заглушки для YouTube/TikTok

## Структура

```
magic-factory/
├── config.example.yaml      # шаблон конфига (копируешь в config.yaml)
├── run_pipeline.py          # запуск всего пайплайна одной командой
├── requirements.txt
├── assets/
│   ├── fonts/               # шрифты для текста (необязательно)
│   └── music/               # положи сюда фоновую музыку (mp3)
├── data/
│   ├── scripts/             # JSON-скрипты от LLM
│   ├── audio/               # MP3 озвучка + SRT
│   ├── stock/               # скачанные клипы Pexels
│   ├── ai_video/            # сгенерированные ИИ-клипы
│   └── subtitles/
├── output/                  # готовые MP4
└── scripts/
    ├── generate_scripts.py  # LLM → JSON-скрипты
    ├── generate_voice.py    # edge-tts → MP3
    ├── fetch_stock.py       # Pexels API → клипы (бесплатно)
    ├── ai_video.py          # Polza Media API → ИИ-клипы (≈1.6 ₽/сек)
    ├── render_video.py      # FFmpeg → финальный MP4 9:16
    └── publish.py           # публикация (Telegram, VK, YouTube, TikTok)
```

## Установка

```bash
pip install -r requirements.txt
# FFmpeg должен быть в PATH: https://ffmpeg.org/download.html
```

## Настройка (один раз)

1. Скопируй шаблон: `cp config.example.yaml config.yaml`
2. Впиши ключи:
   - **polza.api_key** — https://polza.ai/dashboard/api-keys (для скриптов)
   - **pexels.api_key** — https://www.pexels.com/api/ (бесплатный, для стока)
   - **telegram.bot_token** + **channel_id** — бот через @BotFather
   - **vk.access_token** + **group_id** — VK API ключ
3. Положи 1-2 mp3 в `assets/music/`

## Запуск

```bash
# весь пайплайн: 10 видео, публикация в Telegram+VK
# (стоковый режим, если ai_video.enabled: false)
python run_pipeline.py

# включить ИИ-видео: в config.yaml → ai_video.enabled: true
# тогда шаг стока заменяется на генерацию ИИ-клипов (~57 ₽/видео на grok-imagine-video-1-5)
python run_pipeline.py

# ИИ-видео вручную, без влияния на "all"
python run_pipeline.py -s scripts voice ai render

# 5 видео без публикации (сток)
python run_pipeline.py -n 5 -s scripts voice stock render
python run_pipeline.py -n 5 -s scripts voice ai render

# только рендер уже скачанных данных
python run_pipeline.py -s render

# публикация готовых видео
python scripts/publish.py

# перегенерация отдельных шагов
python scripts/generate_scripts.py 20
python scripts/generate_voice.py --all
python scripts/fetch_stock.py --all
python scripts/ai_video.py --all --force   # принудительно пересоздать ИИ-клипы
python scripts/render_video.py --all
```

Источник клипов выбирается `video.source` в конфиге: `stock` (Pexels), `ai` (только ИИ) или `auto` (ИИ клипы если есть, иначе сток). По умолчанию `auto`.

Каждый шаг независим — можно перезапускать отдельно. Ошибка на любом этапе не теряет прогресс (`--steps` продолжает с нужного места).

## Бюджет

| Статья | Стоимость |
|---|---|
| Скрипты (Polza.AI, qwen3.8-flash) | ~1-3 ₽ за 10 скриптов |
| Озвучка (edge-tts) | 0 ₽ |
| Сток-видео (Pexels API) | 0 ₽ |
| ИИ-видео (grok-imagine-video-1-5, 480p) | ~1.62 ₽/сек → ~57 ₽ за ролик 35с |
| ИИ-видео (seedance-2-mini, 480p) | ~2.57 ₽/сек → ~90 ₽ за ролик 35с |
| Сборка (FFmpeg) | 0 ₽ |
| Публикация (Telegram/VK API) | 0 ₽ |
| **Итого (стоковый режим)** | **менее 100 ₽/мес при 10 видео/день** |
| **Итого (ИИ-видео, 10 видео/день)** | **~570 ₽/день** |