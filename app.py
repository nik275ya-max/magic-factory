"""
Magic Factory — Web UI (Streamlit)
Запуск: streamlit run app.py

Инструмент для сборки ОДНОГО видео:
сценарий (нейросеть/вручную) → озвучка → ассеты (drag&drop) → готовый MP4.
"""

import asyncio
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import edge_tts
import openai
import yaml
import streamlit as st

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
SCRIPTS_DIR = DATA / "scripts"
ASSETS_DIR = ROOT / "assets" / "stock"
CONFIG_PATH = ROOT / "config.yaml"

st.set_page_config(
    page_title="Magic Factory",
    page_icon="🏭",
    layout="wide",
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_command(cmd: list[str], cwd: str) -> tuple[bool, list[str]]:
    """Запускает команду и возвращает (статус, строки вывода)."""
    lines: list[str] = []
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    for line in proc.stdout:
        lines.append(line.rstrip())
    proc.wait()
    return proc.returncode == 0, lines


def fmt_size(byte_size: int) -> str:
    mb = byte_size / (1024 * 1024)
    if mb < 1:
        return f"{byte_size / 1024:.0f} KB"
    return f"{mb:.1f} MB"


def get_audio_duration(audio_path: str) -> float:
    """Получает длительность аудиофайла через ffprobe."""
    if not Path(audio_path).exists():
        return 0.0
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
        capture_output=True,
        text=True,
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


# ---------------------------------------------------------------------------
# Сценарий
# ---------------------------------------------------------------------------
SINGLE_SCRIPT_SYSTEM_PROMPT = """Ты — создатель коротких видео про фокусы и магию для TikTok/YouTube Shorts.
Генерируй увлекательные скрипты на русском языке.

Структура видео (30-40 секунд):
1. ХУК (0-3 сек) — цепляющая фраза, которая не даёт листнуть
2. ЗАСТАВКА (3-6 сек) — контекст, интересный факт
3. ОСНОВНАЯ ЧАСТЬ (6-28 сек) — рассказ о фокусе, его истории, как работает
4. ФИНАЛ (28-35 сек) — неожиданный поворот или CTA

Стиль: как будто рассказываешь другу. Без воды.

ВАЖНО: Отвечай ТОЛЬКО валидным JSON без markdown-обёрток."""


def estimate_duration(text: str, rate: str = "+10%") -> float:
    """Оценивает длительность озвучки по количеству слов.

    Средняя скорость русской речи ~2.5 слов/сек на исходной скорости.
    rate="+10%" ускоряет: итоговая скорость 2.5 * 1.1 = 2.75 слов/сек.
    """
    words = len(text.split())
    try:
        num = int("".join(c for c in rate if c.isdigit() or c in "+-"))
        mult = 1 + num / 100.0
    except (ValueError, TypeError):
        mult = 1.0
    wps = 2.5 * mult
    return words / max(wps, 0.5)


def generate_single_script(config: dict, topic: str = "") -> dict:
    """Генерирует ОДИН скрипт через LLM."""
    client = openai.OpenAI(
        api_key=config["polza"]["api_key"],
        base_url=config["polza"]["base_url"],
    )

    topic_line = f"\nТема (придерживайся её): {topic}" if topic.strip() else ""
    user_prompt = f"""Сгенерируй ОДИН уникальный скрипт на тему фокусов и магии.{topic_line}

Категории на выбор: карточные фокусы, монеты, верёвка, ментальная магия,
фокусы с бумагой, рекордные фокусы, Дэвид Копперфильд, история фокусов.

Верни JSON-объект (НЕ массив):
{{
  "id": "уникальный_id",
  "category": "категория",
  "title": "короткий заголовок для видео",
  "hook": "цепляющая первая фраза (0-3 сек)",
  "body": "основной текст озвучки (весь текст целиком)",
  "cta": "призыв к действию в конце",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "text_overlays": [
    {{"time_sec": 0, "text": "ТЕКСТ НА ЭКРАНЕ", "style": "hook"}},
    {{"time_sec": 15, "text": "ДРУГОЙ ТЕКСТ", "style": "info"}}
  ],
  "hashtags": ["#фокусы", "#магия", "#иллюзии"]
}}

Все поля обязательны. Текст озвучки (hook+body+cta) — 250-350 слов (30-40 сек).
Keywords — на английском. text_overlays — ключевые фразы на экране."""

    response = client.chat.completions.create(
        model=config["polza"]["model"],
        messages=[
            {"role": "system", "content": SINGLE_SCRIPT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=config["polza"].get("temperature", 0.9),
        max_tokens=config["polza"].get("max_tokens", 4000),
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])

    script = json.loads(raw)
    script.setdefault("id", str(uuid.uuid4()))
    script["generated_at"] = datetime.now().isoformat()
    script["status"] = "new"
    return script


# ---------------------------------------------------------------------------
# Озвучка
# ---------------------------------------------------------------------------
async def _tts(text: str, output_path: str, voice: str, rate: str, volume: str):
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    await communicate.save(output_path)


def generate_voice_for_script(script: dict, config: dict, data_dir: Path) -> str:
    """Генерирует озвучку для скрипта, возвращает путь к MP3."""
    script_id = script["id"][:8]
    mp3_path = data_dir / "audio" / f"{script_id}.mp3"
    mp3_path.parent.mkdir(parents=True, exist_ok=True)

    parts = [p for p in (script.get("hook"), script.get("body"), script.get("cta")) if p]
    text = " ".join(parts)

    voice_cfg = config["voice"]
    asyncio.run(
        _tts(
            text,
            str(mp3_path),
            voice_cfg["voice_name"],
            voice_cfg["rate"],
            voice_cfg["volume"],
        )
    )
    return str(mp3_path)


def get_overlay_table(script: dict) -> list[dict]:
    return [
        {"time_sec": ov.get("time_sec", 0), "text": ov.get("text", ""), "style": ov.get("style", "info")}
        for ov in script.get("text_overlays", [])
    ]


def save_single_script(script: dict, scripts_dir: Path) -> Path:
    """Сохраняет скрипт в data/scripts/{id}.json."""
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / f"{script['id'][:8]}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------------
# Состояние мастера
# ---------------------------------------------------------------------------
st.session_state.setdefault("sv_script", None)
st.session_state.setdefault("sv_script_file", None)
st.session_state.setdefault("sv_mp3", None)
st.session_state.setdefault("sv_mp3_dur", None)
st.session_state.setdefault("sv_upload_ver", 0)

config = load_config()
voice_cfg = config.get("voice", {})

# ---------------------------------------------------------------------------
# 🎯 Мастер: одно видео
# ---------------------------------------------------------------------------
st.title("🎯 Одно видео")
st.caption("Сценарий → озвучка → ассеты (drag&drop) → готовый ролик")

# ---------- Шаг 1: сценарий ----------
st.subheader("1. 📝 Сценарий")

origin = st.radio("Откуда берём текст?", ["✨ Нейросеть", "✍️ Вручную"], horizontal=True)

if origin == "✨ Нейросеть":
    col_topic, col_gen = st.columns([3, 1])
    topic = col_topic.text_input("Подсказка / тема (необязательно)", placeholder="напр. фокус с исчезновением монеты")
    if col_gen.button("⚡ Сгенерировать", type="primary", use_container_width=True):
        with st.spinner("Нейросеть пишет сценарий..."):
            try:
                script = generate_single_script(config, topic)
                st.session_state.sv_script = script
                st.session_state.sv_script_file = None
                st.session_state.sv_mp3 = None
                st.session_state.sv_mp3_dur = None
                st.success("Сценарий готов!")
            except Exception as e:
                st.error(f"Ошибка генерации: {e}")

elif origin == "✍️ Вручную":
    st.info("Заполни текст сценария:")

    if st.session_state.sv_script:
        s = st.session_state.sv_script
        defaults = dict(
            title=s.get("title", ""),
            hook=s.get("hook", ""),
            body=s.get("body", ""),
            cta=s.get("cta", ""),
            category=s.get("category", ""),
        )
    else:
        defaults = dict(title="", hook="", body="", cta="", category="карточные фокусы")

    m_title = st.text_input("Заголовок", value=defaults["title"])
    m_category = st.text_input("Категория", value=defaults["category"])
    m_hook = st.text_area("Хук (первые 3 сек, цепляет)", value=defaults["hook"], height=60)
    m_body = st.text_area("Основной текст озвучки", value=defaults["body"], height=160)
    m_cta = st.text_area("Призыв к действию (финал)", value=defaults["cta"], height=60)

    if st.button("💾 Сохранить сценарий", type="primary"):
        if not (m_hook.strip() or m_body.strip()):
            st.error("Текст пустой — напиши хотя бы хук или основную часть")
        else:
            prev = st.session_state.sv_script or {}
            script = {
                "id": prev.get("id") or str(uuid.uuid4()),
                "category": m_category or "ручной",
                "title": m_title or m_hook[:40],
                "hook": m_hook.strip(),
                "body": m_body.strip(),
                "cta": m_cta.strip(),
                "keywords": prev.get("keywords", []),
                "text_overlays": prev.get("text_overlays", []),
                "hashtags": prev.get("hashtags", []),
                "generated_at": datetime.now().isoformat(),
                "status": "new",
            }
            st.session_state.sv_script = script
            st.session_state.sv_script_file = None
            st.session_state.sv_mp3 = None
            st.session_state.sv_mp3_dur = None
            st.success("Сценарий сохранён")

script = st.session_state.sv_script

if script:
    script_id = script["id"][:8]

    # Полный текст (hook + body + cta)
    all_text = " ".join(
        [p for p in (script.get("hook"), script.get("body"), script.get("cta")) if p]
    )
    est = estimate_duration(all_text, voice_cfg.get("rate", "+10%"))
    words = len(all_text.split())

    col_est1, col_est2, col_est3 = st.columns(3)
    col_est1.metric("⏱ Оценка длительности", f"~{int(est)} сек")
    col_est2.metric("📝 Слов", words)
    col_est3.metric("🎙 Голос", voice_cfg.get("voice_name", ""))

    # Редактирование оверлеев
    with st.expander("🖼 Текстовые оверлеи (какие фразы на экране)"):
        overlays = get_overlay_table(script)
        if not overlays:
            overlays = [{"time_sec": 0, "text": "ТЕКСТ НА ЭКРАНЕ", "style": "hook"}]
        edited = st.data_editor(
            overlays,
            column_config={
                "time_sec": st.column_config.NumberColumn("Секунда", min_value=0, max_value=120),
                "text": st.column_config.TextColumn("Текст"),
                "style": st.column_config.SelectboxColumn("Стиль", options=["hook", "info"]),
            },
            num_rows="dynamic",
            hide_index=True,
        )
        if st.button("💾 Сохранить оверлеи"):
            script["text_overlays"] = [
                {"time_sec": int(r["time_sec"]), "text": str(r["text"]), "style": str(r["style"])}
                for r in edited
                if r.get("text")
            ]
            st.session_state.sv_script = script
            st.success("Оверлеи сохранены")

    # ---------- Шаг 2: озвучка ----------
    st.divider()
    st.subheader("2. 🎙 Озвучка")

    mp3_path = st.session_state.sv_mp3
    mp3_exists = mp3_path and Path(mp3_path).exists()

    col_vo1, col_vo2 = st.columns([1, 2])
    if col_vo1.button("🎙 Озвучить", type="primary", use_container_width=True):
        with st.spinner("Генерирую озвучку..."):
            try:
                mp3 = generate_voice_for_script(script, config, DATA)
                st.session_state.sv_mp3 = mp3
                st.session_state.sv_mp3_dur = get_audio_duration(mp3)
                st.success("Озвучка готова!")
            except Exception as e:
                st.error(f"Ошибка озвучки: {e}")

    if mp3_exists:
        real_dur = st.session_state.sv_mp3_dur or get_audio_duration(mp3_path)
        size_mb = fmt_size(Path(mp3_path).stat().st_size)
        st.success(f"✅ Озвучка: {real_dur:.1f} сек • {size_mb}")
        st.audio(mp3_path)

    # ---------- Шаг 3: ассеты ----------
    st.divider()
    st.subheader("3. 📦 Ассеты (видео-нарезки)")

    assets_target = ASSETS_DIR / script_id
    existing_clips = sorted(list(assets_target.glob("*.mp4"))) if assets_target.exists() else []

    if existing_clips:
        st.success(f"Уже есть {len(existing_clips)} клипов в `assets/stock/{script_id}/`")
        for c in existing_clips:
            st.caption(f"  • {c.name} — {fmt_size(c.stat().st_size)}")
    else:
        st.info(f"Папка `assets/stock/{script_id}/` пуста — загрузи клипы ниже")

    uploaded_clips = st.file_uploader(
        "Перетащи MP4 сюда (drag & drop)",
        type=["mp4", "mov", "avi", "mkv"],
        accept_multiple_files=True,
        key=f"sv_upload_{script_id}_{st.session_state.sv_upload_ver}",
    )
    if uploaded_clips:
        assets_target.mkdir(parents=True, exist_ok=True)
        saved = 0
        for f in uploaded_clips:
            dest = assets_target / f.name
            with open(dest, "wb") as out:
                out.write(f.getbuffer())
            saved += 1
        st.session_state.sv_upload_ver += 1
        st.success(f"Загружено {saved} клипов в `assets/stock/{script_id}/`")
        st.rerun()

    # ---------- Шаг 4: сборка ----------
    st.divider()
    st.subheader("4. 🎬 Сборка видео")

    col_b1, col_b2 = st.columns([1, 3])
    if col_b1.button("🚀 Собрать видео", type="primary", use_container_width=True):
        if not mp3_exists:
            with st.spinner("Сначала генерирую озвучку..."):
                try:
                    mp3 = generate_voice_for_script(script, config, DATA)
                    st.session_state.sv_mp3 = mp3
                    st.session_state.sv_mp3_dur = get_audio_duration(mp3)
                except Exception as e:
                    st.error(f"Ошибка озвучки: {e}")
                    mp3 = None
            if mp3 is None:
                st.stop()

        # Сохраняем скрипт в data/scripts/
        script_file = save_single_script(script, SCRIPTS_DIR)
        st.session_state.sv_script_file = str(script_file)

        with st.spinner("Собираю видео..."):
            ok, lines = run_command(
                [sys.executable, str(ROOT / "scripts" / "render_video.py"), script_file.name],
                str(ROOT),
            )

        result_video = OUTPUT / f"{script_id}_final.mp4"
        if ok and result_video.exists():
            st.success("🎉 Видео готово!")
            st.video(str(result_video))
            with open(result_video, "rb") as f:
                st.download_button("⬇️ Скачать MP4", data=f, file_name=result_video.name, mime="video/mp4")
            st.code("\n".join(lines[-60:]), language="bash")
        else:
            st.error("Сборка не удалась, смотри лог:")
            st.code("\n".join(lines[-80:]), language="bash")