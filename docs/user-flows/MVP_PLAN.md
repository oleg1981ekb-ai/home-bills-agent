# User Flow Roadmap — MVP (Anapa Water Agent v1.1)

Источник: `docs/user-flows/billing-cycle.md`, `src/home_bills_agent/`, `SPEC/`.

## 1. Матрица готовности сценариев (Текущий статус)

| Этап | Сценарий | Текущий статус | Комментарий |
|---|---|---|---|
| Авторизация | WhitelistMiddleware → allowed → хендлер | ✅ Работает | Проверка `is_user_allowed` по `TELEGRAM_USER_ID` / whitelist; silent reject для чужих. |
| Ввод текстом | `/start` → `/status` → `msg_reading` (`^\d+$`) → `_handle_reading` | ✅ Работает | Валидация целого числа, окно 1–25, раз в сутки, `value >= last_reading`, аномалия. |
| Распознавание фото | `msg_photo` → `_download_photo` → `recognize_reading` → `value is None` → confirm | ⚠️ Частично | Чек-листы/валидация на месте, но распознавание на реальных фото + реальном ключе LLM требует живого ключа. |
| Валидация / Аномалии | `_check_window`, `_check_once_per_day`, `value < last_reading`, `_check_anomaly` | ✅ Работает | Anomaly-флаг → `AWAITING_ANOMALY_CONFIRMATION` → подтверждение → `READING_SENT`. |
| Интеграция с ЛК | `StubVodokanalClient.add_counter_value` → `HttpxVodokanalClient` | ⚠️ На стабах | DRY_RUN: мгновенный успех. Реальный клиент: заглушки `login/get_counter_readings/add_counter_value/get_debt` (требует реальных логинов и HTML-парсинга). |
| Оплата А3 | `AWAITING_PAYMENT → PAID`, cancel `PAID → CANCELLED`, ссылки/кнопки | ✅ Работает | Логика бота: ссылки, `mark_paid`, `cancel_payment`, `payment.claimed/cancelled`. Оплата сама по А3 — вне кода. |
| Сверка долга | scheduler `check_due_reminders` → проверка/перевод в `PAID`/`MANUAL_REVIEW` | ⚠️ Частично | Слой планировщика есть; реальная сверка через реальный клиент ЛК — нет. |
| Ручной разбор | → `MANUAL_REVIEW` | ✅ Частично | Отправка ЛК упала → `MANUAL_REVIEW`; исчерпание попыток/нештатная ситуация — остались как статус. |

## 2. Этапы до релиза MVP (Milestones)

### Этап 1 — Core Happy Path (без заглушек
Для минимально работающего MVP без стабов.

- Подключить реальный `HttpxVodokanalClient` (login, history, debt, add) вместо stub/заглушек.
- Подключить реальный vision-провайдер (`ANTHROPIC_API_KEY` или `OPENROUTER_API_KEY`).
- Убедиться, что бот реально пишет пользователю на старт/состояния/оплату.
- Прогнать сквозной сценарий `Ввод → Подтверждение → Отправка → Оплата → PAID → Сверка` на живом аккаунте.

### Этап 2 — Edge Cases & Guardrails (до выхода реальных пользователей

- Обработать `add_counter_value` fallback → `MANUAL_REVIEW`.
- Обработать таймауты/ошибки LLM (`value is None`) и повторное распознавание.
- Защита от зависших статусов FSM (в т.ч. `ACCRUAL_PENDING`/`AWAITING_PAYMENT`) и нештатные переходы.
- Управление исчерпанием попыток → `MANUAL_REVIEW`.

### Этап 3 — Post-MVP / Backlog

- UX: повторные напоминания, подробнее логи.
- Автоматизация: повторные проверки оплаты, более плотная сверка долга.
- Архитектура: перейти от в памяти/SQLite/FSM к более жёсткой модели.

## 3. Критерии приёмки (Definition of Done)

- [ ] `ruff check .` — 0 ошибок.
- [ ] `pytest` — все тесты pass.
- [ ] `make ai-smoke` — OK.
- [ ] `DRY_RUN=false` + реальные секреты ЛК/LLM.
- [ ] Сквозной e2e-сценарий на реальном пользователе: `Ввод → Оплата → PAID → Сверка`.
- [ ] Логирование и маскировка в `events`.
- [ ] Проверка автозапуска и резервной копии SQLite.