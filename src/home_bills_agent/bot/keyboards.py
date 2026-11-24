from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_backend_menu_keyboard(current_backend: str) -> InlineKeyboardMarkup:
    """
    Inline-клавиатура меню выбора бэкенда Vodokanal для Telegram-админа.

    :param current_backend: Текущий выбранный бэкенд ("httpx" или "playwright").
    :return: InlineKeyboardMarkup.
    """
    # Обозначаем выбранный текущий бэкенд галочкой ✅
    httpx_btn = InlineKeyboardButton(
        text="✅ Прямой HTTP (быстрый)" if current_backend == "httpx" else "Прямой HTTP (быстрый)",
        callback_data="admin:backend:httpx",
    )
    pw_btn = InlineKeyboardButton(
        text="✅ Браузерный Playwright (запасной вариант)" if current_backend == "playwright" else "Браузерный Playwright (запасной вариант)",
        callback_data="admin:backend:playwright",
    )
    back_btn = InlineKeyboardButton(text="↩️ Назад", callback_data="admin:back")

    return InlineKeyboardMarkup(inline_keyboard=[[httpx_btn, pw_btn], [back_btn]])