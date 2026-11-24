#!/usr/bin/env python3
"""
TTY-меню выбора бэкенда Vodokanal (httpx / Playwright).

Использование:
    python3 scripts/select_backend.py

Зависимости:
    questionary>=2.0, rich>=13.0
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

DEFAULT_BACKEND = "httpx"
CONFIG_PATH = Path(".kilo/config.yaml")

BACKEND_LABELS = {
    "httpx": "Прямой HTTP (быстрый)",
    "playwright": "Браузерный Playwright (запасной вариант)",
}

BACKEND_DESCRIPTIONS = {
    "httpx": "Прямые HTTP-запросы через httpx + HTML-парсинг. Быстро, дёшево, стабильно.",
    "playwright": "Управление браузером Playwright. Тяжелее, но обходит сложную защиту.",
}

console = Console()


def load_config() -> dict:
    """Загрузить конфигурацию бэкенда из .kilo/config.yaml."""
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "backend" in data:
                return {"backend": data["backend"]}
        except (json.JSONDecodeError, OSError):
            pass
    return {"backend": DEFAULT_BACKEND}


def save_config(config: dict) -> None:
    """Сохранить конфигурацию бэкенда в .kilo/config.yaml."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def show_current_status(current: str) -> None:
    """Вывести текущий статус выбора бэкенда."""
    table = Table(show_header=False, box=None)
    table.add_row("Текущий бэкенд:", f"{BACKEND_LABELS.get(current, current)} ✅")
    table.add_row("Описание:", BACKEND_DESCRIPTIONS.get(current, "—"))
    console.print(table)


def select_backend(current: str) -> str | None:
    """Показать меню выбора бэкенда через questionary."""
    choices = []
    for backend in ("httpx", "playwright"):
        label = BACKEND_LABELS[backend]
        if backend == current:
            label = f"✅ {label} (текущий)"
        choices.append(questionary.Choice(title=label, value=backend))

    choice = questionary.select(
        "Выберите бэкенд провайдера Vodokanal:",
        choices=choices,
        default=current,
    ).ask()
    return choice


def run_diagonal_reading() -> None:
    """Запустить diagonal_reading.py для быстрой проверки проекта."""
    console.print("\n[bold]Чтение по диагонали — быстрая проверка ключевых разделов[/bold]\n")
    import subprocess
    try:
        subprocess.run(
            [sys.executable, "scripts/diagonal_reading.py"],
            check=False,
        )
    except FileNotFoundError:
        console.print("[yellow]diagonal_reading.py не найден, пропускаю.[/yellow]")


def main() -> int:
    """Главная функция CLI-меню."""
    config = load_config()
    current = config["backend"]

    console.print(
        Panel.fit(
            "[bold]Vodokanal Client — выбор бэкенда[/bold]\n"
            "httpx — прямой HTTP · Playwright — браузерный",
            border_style="blue",
        )
    )
    show_current_status(current)

    new_backend = select_backend(current)
    if new_backend is None:
        console.print("[yellow]Выбор отменён.[/yellow]")
        return 0

    if new_backend != current:
        config["backend"] = new_backend
        save_config(config)
        console.print(f"[green]Бэкенд переключён на: {BACKEND_LABELS[new_backend]}[/green]")
    else:
        console.print("[dim]Бэкенд не изменился.[/dim]")

    if questionary.confirm("Запустить «Чтение по диагонали»?", default=False).ask():
        run_diagonal_reading()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())