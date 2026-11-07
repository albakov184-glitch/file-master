from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from app.config import BOT_API_URL, BOT_TOKEN


def make_bot() -> Bot:
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather.")
    session = None
    if BOT_API_URL:  # свой сервер Bot API — файлы до 2 ГБ
        session = AiohttpSession(api=TelegramAPIServer.from_base(BOT_API_URL, is_local=True))
    return Bot(BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
