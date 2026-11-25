# Документация пользовательских потоков

Эта папка содержит картографирование реальных пользовательских сценариев по коду Telegram-бота **Anapa Water Agent v1.1**.

## Документы

| Файл | Описание |
|------|----------|
| [billing-cycle.md](./billing-cycle.md) | Жизненный цикл биллинга: от входа (WhitelistMiddleware) и ввода показаний (текст / фото) до оплаты по ссылке А3, `PAID` и сверки долга. Содержит таблицу Happy Path, развитие ошибок и Mermaid-схему. |

## Статусы FSM (доступные состояния цикла)

Источник: `src/home_bills_agent/storage/fsm.py:14-21`

| Статус | Значение |
|--------|----------|
| `WAITING_READING` | Цикл создан, ожидается показание |
| `AWAITING_ANOMALY_CONFIRMATION` | Расход аномальный или значение распознано по фото, ждём подтверждения пользователя |
| `READING_SENT` | Показание отправлено в ЛК, идёт проверка |
| `ACCRUAL_PENDING` | Долг после отправки не изменился, повторные проверки |
| `AWAITING_PAYMENT` | Ссылка на оплату отправлена |
| `PAID` | Пользователь подтвердил оплату (и долг подтверждённо снизился) |
| `CANCELLED` | Отмена пользователем |
| `MANUAL_REVIEW` | Исчерпаны попытки или нештатная ситуация |

## Допустимые переходы (сокращённо)

Источник: `src/home_bills_agent/storage/fsm.py:26-51`

- `WAITING_READING → READING_SENT / AWAITING_ANOMALY_CONFIRMATION / CANCELLED`
- `AWAITING_ANOMALY_CONFIRMATION → READING_SENT / WAITING_READING / CANCELLED`
- `READING_SENT → AWAITING_PAYMENT / ACCRUAL_PENDING`
- `ACCRUAL_PENDING → AWAITING_PAYMENT / MANUAL_REVIEW`
- `AWAITING_PAYMENT → PAID`
- `PAID → CANCELLED` (отмена ошибочно указанной оплаты)
- `PAID`, `CANCELLED`, `MANUAL_REVIEW` — терминальные (нет исходящих переходов)

## Ключевые файлы

- `src/home_bills_agent/bot/middleware.py` — WhitelistMiddleware
- `src/home_bills_agent/bot/handlers.py` — все хендлеры (команды, чтение показаний, фото, оплата, отмена)
- `src/home_bills_agent/assistant/vision.py` — распознавание фото (Anthropic / OpenRouter)
- `src/home_bills_agent/storage/fsm.py` — FSM и переходы состояний
- `src/home_bills_agent/scheduler/jobs.py` — напоминания, сверка начислений, проверка оплаты _
- `src/home_bills_agent/config.py` — настройки, whitelist, DRY_RUN
