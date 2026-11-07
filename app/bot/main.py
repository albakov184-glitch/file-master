"""Telegram-бот: принимает файлы и ставит задачи в очередь. Запуск: python -m app.bot.main"""
import asyncio
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from arq import create_pool
from arq.connections import RedisSettings

from app import db
from app.bot.handlers import router
from app.config import REDIS_URL
from app.telegram import make_bot


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_db()
    bot = make_bot()
    dp = Dispatcher(storage=RedisStorage.from_url(REDIS_URL))
    dp["arq"] = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
        BotCommand(command="merge", description="Объединить файлы в PDF"),
        BotCommand(command="history", description="История обработанных файлов"),
        BotCommand(command="formats", description="Поддерживаемые форматы"),
        BotCommand(command="help", description="Помощь"),
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
