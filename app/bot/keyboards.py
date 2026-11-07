from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import human_size
from app.db import Job, Upload
from app.formats import ACTION_LABELS, actions_for, targets_for

BTN_MERGE = "📎 Объединить в PDF"
BTN_HISTORY = "🕘 История"
BTN_FORMATS = "📋 Форматы"
BTN_HELP = "ℹ️ Помощь"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_MERGE), KeyboardButton(text=BTN_HISTORY)],
                  [KeyboardButton(text=BTN_FORMATS), KeyboardButton(text=BTN_HELP)]],
        resize_keyboard=True,
        input_field_placeholder="Пришлите файл…",
    )


def actions_kb(up: Upload) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for act in actions_for(up.kind):
        if act == "convert" and not targets_for(up.kind, up.ext):
            continue
        kb.button(text=ACTION_LABELS[act], callback_data=f"a:{up.id}:{act}")
    kb.adjust(1)
    return kb.as_markup()


def targets_kb(up: Upload) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in targets_for(up.kind, up.ext):
        kb.button(text=t.upper(), callback_data=f"c:{up.id}:{t}")
    kb.adjust(3)
    back = InlineKeyboardBuilder()
    back.button(text="↩️ Назад", callback_data=f"b:{up.id}")
    kb.attach(back)
    return kb.as_markup()


def merge_kb(count: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if count >= 2:
        kb.button(text=f"✅ Объединить ({count})", callback_data="m:go")
    kb.button(text="❌ Отмена", callback_data="m:cancel")
    kb.adjust(1)
    return kb.as_markup()


def history_kb(jobs: list[Job]) -> InlineKeyboardMarkup | None:
    kb = InlineKeyboardBuilder()
    for j in jobs:
        if j.status == "done" and j.result_file_ids:
            title = f"📥 #{j.id} {j.result_name}"
            title = (title[:45] + "…" if len(title) > 46 else title) + f" · {human_size(j.result_size)}"
            kb.button(text=title, callback_data=f"h:{j.id}")
    kb.adjust(1)
    markup = kb.as_markup()
    return markup if markup.inline_keyboard else None
