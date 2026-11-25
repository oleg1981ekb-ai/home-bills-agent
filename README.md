# Home Bills Agent (Anapa Water Agent v1.1)

Telegram-бот для приёма показаний водяных счётчиков АО «Анапа Водоканал», напоминаний, проверки аномалий, автоматической отправки в личный кабинет и интеграции оплаты через сервис А3.

## Документация

- [User flows / жизненный цикл биллинга](./docs/user-flows/README.md)
- [Billing cycle — Happy Path, edge cases, Mermaid-диаграмма](./docs/user-flows/billing-cycle.md)

## Команды

- `/start` — приветствие и подсказка по показанию.
- `/help` — доступные команды.
- `/status` — текущий статус цикла.

## Модели и качество

- Lint: `ruff check .`
- Tests: `python3.15 -m pytest tests/ -q`
- E2E (full billing cycle): `python3.15 -m pytest tests/test_e2e.py -v`
- AI infra smoke: `make ai-smoke`

## Развёртывание

- `DRY_RUN=true` — режим имитации (без реальных запросов к ЛК и LLM).
- `AUTO_SEND=false` — подтверждение и оплата пользователем.

Для запуска бота используйте `src/home_bills_agent/main.py` или Docker-контейнер (`Dockerfile`, `docker-compose.yml`).
