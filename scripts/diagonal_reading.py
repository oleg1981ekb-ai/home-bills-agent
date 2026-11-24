#!/usr/bin/env python3
"""
Чтение по диагонали — утилита для быстрого прогона по ключевым разделам проекта.

Показывает только «диагональ»: заголовки, ключевые строки, статусы вето,
константы, public API — без погружения в детали реализации.

Usage:
    python3 scripts/diagonal_reading.py [path]
"""

from __future__ import annotations

import sys
from pathlib import Path


def scan_file(path: Path) -> list[str]:
    """Вернуть «диагональ» файла: заголовки, ключевые строки, константы."""
    highlights: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return highlights

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("# ", "## ", "class ", "def ", "VETO", "TODO", "FIXME", "OPTIMIZED")):
            highlights.append(f"{path}:{lineno}: {stripped[:100]}")
    return highlights


def scan_directory(root: Path) -> list[str]:
    results: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".md", ".toml", ".yaml", ".yml"}:
            results.extend(scan_file(path))
    return results


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    lines = scan_directory(root)
    if not lines:
        print("Диагональ пуста — подозрительно тихо.")
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())