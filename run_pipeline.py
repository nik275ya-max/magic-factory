"""
Magic Factory — Главный оркестратор
Запускает полный пайплайн: скрипты → озвучка → сток → сборка → публикация
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import yaml

ROOT = Path(__file__).parent


def load_config() -> dict:
    config_path = ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_step(name: str, script: str, args: list[str] = None) -> bool:
    """Запускает один шаг пайплайна."""
    print(f"\n{'='*60}")
    print(f"  ШАГ: {name}")
    print(f"{'='*60}\n")

    cmd = [sys.executable, script] + (args or [])
    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        print(f"\n[!] Шаг '{name}' завершился с ошибкой (код {result.returncode})")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Magic Factory Pipeline")
    parser.add_argument(
        "--count", "-n", type=int, default=None,
        help="Количество видео для генерации (по умолчанию из config.yaml)",
    )
    parser.add_argument(
        "--steps", "-s", nargs="+",
        choices=["scripts", "voice", "stock", "ai", "render", "publish", "all"],
        default=["all"],
        help="Какие шаги выполнять",
    )
    parser.add_argument(
        "--platforms", "-p", nargs="+",
        choices=["telegram", "vk", "youtube", "tiktok", "all"],
        default=["telegram", "vk"],
        help="Платформы для публикации",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Показать план без выполнения",
    )

    args = parser.parse_args()
    config = load_config()

    count = args.count or config["pipeline"]["batch_size"]
    steps = args.steps
    run_all = "all" in steps

    scripts_dir = ROOT / "scripts"

    # План выполнения
    plan = []

    ai_enabled = bool(config.get("ai_video", {}).get("enabled", False))

    if run_all or "scripts" in steps:
        plan.append(("scripts", "Генерация скриптов", str(scripts_dir / "generate_scripts.py"), [str(count)]))
    if run_all or "voice" in steps:
        plan.append(("voice", "Генерация озвучки", str(scripts_dir / "generate_voice.py"), ["--all"]))

    # В режиме "all": при включённом ai_video генерируем ИИ-клипы ВМЕСТО стока.
    # По умолчанию рендер предпочтёт ИИ-клипы (video.source: auto).
    if run_all:
        if ai_enabled:
            plan.append(("ai", "Генерация ИИ-видео", str(scripts_dir / "ai_video.py"), ["--all"]))
        else:
            plan.append(("stock", "Скачивание стоковых видео", str(scripts_dir / "fetch_stock.py"), ["--all"]))
    else:
        if "stock" in steps:
            plan.append(("stock", "Скачивание стоковых видео", str(scripts_dir / "fetch_stock.py"), ["--all"]))
        if "ai" in steps:
            plan.append(("ai", "Генерация ИИ-видео", str(scripts_dir / "ai_video.py"), ["--all", "--force"]))

    if run_all or "render" in steps:
        plan.append(("render", "Сборка видео", str(scripts_dir / "render_video.py"), ["--all"]))
    # Публикация только если явно запрошен шаг (-s publish) ИЛИ включён auto_publish.
    auto_publish = bool(config.get("pipeline", {}).get("auto_publish", False))
    if run_all:
        if auto_publish:
            plan.append(("publish", "Публикация", str(scripts_dir / "publish.py"), ["--all"] + args.platforms))
        else:
            print("[i] auto_publish=false — публикация пропущена. "
                  "Для постинга: python run_pipeline.py -s publish")
    elif "publish" in steps:
        plan.append(("publish", "Публикация", str(scripts_dir / "publish.py"), ["--all"] + args.platforms))

    # Показываем план
    print("""
========================================
  MAGIC FACTORY - Контент-завод
========================================
""")
    print(f"  Видео для производства: {count}")
    print(f"  Платформы: {', '.join(args.platforms)}")
    print()
    print("  План выполнения:")
    for i, (key, name, script, script_args) in enumerate(plan, 1):
        print(f"    {i}. {name}")
    print()

    if args.dry_run:
        print("[DRY RUN] План выше. Запуск не выполняется.")
        return

    # Запуск
    start_time = time.time()
    total_steps = len(plan)
    completed = 0

    for i, (key, name, script, script_args) in enumerate(plan, 1):
        print(f"\n[{i}/{total_steps}] {name}...")

        success = run_step(name, script, script_args)
        if success:
            completed += 1
        else:
            print(f"\n[!] Пайплайн остановлен на шаге '{name}'")
            print("    Исправь ошибку и запусти снова с --steps чтобы начать с нужного шага")
            break

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print(f"""
========================================
  ГОТОВО!
========================================
  Выполнено шагов: {completed}/{total_steps}
  Время: {minutes}м {seconds}с
  Видео: output/*_final.mp4
""")


if __name__ == "__main__":
    main()
