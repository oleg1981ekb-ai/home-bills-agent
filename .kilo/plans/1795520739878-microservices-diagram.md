# Plan: HTML-схема микросервисной декомпозиции (home-bills-agent)

## Context
- Проект: Home Bills Agent / Anapa Water Agent v1.1 — Telegram-ассистент передачи показаний и оплаты ЖКХ.
- Текущая архитектура — монолит в одном Docker-контейнере (Python 3.12, aiogram 3, httpx, SQLite/SQLAlchemy, APScheduler, Anthropic API).
- Источник правды: `SPEC/Спецификация_Anapa_Water_Agent_v1.1.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`.
- Модули монолита: bot, assistant, vodokanal_client (providers/anapa_vodokanal), payment, storage, scheduler.

## Goal
Сгенерировать HTML-файл со встроенным SVG — наглядная схема разделения монолита на микросервисы в тёмной теме VS Code. Блоки разнесены с запасом; стрелки REST/gRPC и брокера сообщений обходят блоки и не перекрывают текст. Сохранить в `/tmp/arch-diagram.html` и вывести путь.

## Confirmed requirements
- HTML + встроенный SVG одним файлом, без внешних зависимостей (CDN/шрифты не нужны).
- Тёмная тема (палитра VS Code: фон `#1e1e1e`, панели `#252526`, акцент `#0078d4`, текст `#cccccc`).
- Содержание: декомпозиция монолита на микросервисы.
- Блоки с достаточным отступом друг от друга (зазор ≥ 40 px).
- Типы связей: REST/gRPC (синхронные) и message broker (асинхронные); разные стили линий/стрелок.
- Стрелки маршрутизируются в обход блоков и не пересекают подписи.
- Deliverable: `/tmp/arch-diagram.html` + путь к файлу в ответе.

## Proposed decomposition (recommended)
| Микросервис | Происхождение (модуль монолита) | Назначение | Протокол |
| --- | --- | --- | --- |
| bot-orchestrator | bot + scheduler | Telegram UX, FSM-оркестрация, напоминания | REST/gRPC к сервисам; broker для событий |
| provider-integration | vodokanal_client (providers/anapa_vodokanal) | Вход в ЛК, чтение/передача показаний | REST/gRPC |
| ocr-assistant | assistant | OCR фото счётчика (`claude-sonnet-4-5`) | REST/gRPC |
| payment | payment | Ссылка А3, проверка долга | REST/gRPC |
| storage-events | storage | billing_cycles, readings_cache, events | broker |

Поток данных: Telegram → `bot-orchestrator` → `ocr-assistant` (фото) / `provider-integration` (показания) → `storage-events`; `bot-orchestrator` → `payment` (ссылка А3); асинхронные события — через брокер.

## Tasks (for implementation agent)
1. Проанализировать структуру проекта (модули из `docs/ARCHITECTURE.md` и спецификации).
2. Спроектировать координатную сетку SVG: ≥ 5 блоков, зазор ≥ 40 px между блоками.
3. Сгенерировать `/tmp/arch-diagram.html`: HTML + inline SVG с фиксированными координатами, rounded rect, подписи, легенда (REST/gRPC vs broker).
4. Маршрутизировать рёбра ортогональными путями (waypoints) в обход блоков; подписи размещать вне линий и блоков.
5. Проверить отсутствие наложения текста и пересечения стрелок с блоками.
6. Вывести путь `/tmp/arch-diagram.html`.

## Risks & mitigations
- Наложение текста/стрелок → фиксированная сетка, elbow routing, отступы.
- «Код с осторожностью» → только генерация статического HTML, без изменений исходников проекта.

## Validation
- Открыть `/tmp/arch-diagram.html` в браузере или VS Code и визуально проверить рендер.
- Убедиться, что стрелки не пересекают текст и блоки; присутствует легенда.

## Out of scope
- Реальная реализация/миграция микросервисов; изменение исходного кода приложения.