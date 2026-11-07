"""Воркер очереди (arq + Redis): скачивает файлы, обрабатывает, отправляет результат.
Запуск: arq app.worker.WorkerSettings"""
import asyncio
import logging
import re
import shutil
import time
from html import escape
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaDocument
from arq import func
from arq.connections import RedisSettings

from app import db
from app.config import (JOB_TIMEOUT, MAX_DOWNLOAD, MAX_UPLOAD, REDIS_URL, WORK_DIR, WORKER_CONCURRENCY,
                        human_size)
from app.formats import op_label
from app.processing import process
from app.processing.common import UserError
from app.telegram import make_bot

log = logging.getLogger("worker")


def safe_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .") or "file"
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:100] + dot + ext) if dot and len(ext) <= 10 else name[:120]
    return name


def _escape_trim(text: str, limit: int) -> str:
    esc = escape(text)
    if len(esc) <= limit:
        return esc
    cut = esc[:limit]
    amp = cut.rfind("&")
    if amp > cut.rfind(";"):  # не разрезаем HTML-сущность вида &amp;
        cut = cut[:amp]
    return cut + "…"


async def edit_status(bot: Bot, job: db.Job, text: str) -> None:
    if not job.status_msg_id:
        return
    try:
        await bot.edit_message_text(text=text, chat_id=job.chat_id, message_id=job.status_msg_id)
    except TelegramBadRequest:
        pass  # сообщение удалено или текст не изменился


async def download(bot: Bot, file_id: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        await bot.download(file_id, destination=dest)
    except TelegramBadRequest as e:
        if "too big" in str(e).lower():
            raise UserError(f"Файл больше {human_size(MAX_DOWNLOAD)} — Telegram не даёт боту его скачать") from None
        raise


async def send_results(bot: Bot, job: db.Job, files: list[Path], caption: str) -> list[str]:
    for f in files:
        if f.stat().st_size > MAX_UPLOAD:
            raise UserError(f"Результат ({human_size(f.stat().st_size)}) больше лимита Telegram "
                            f"{human_size(MAX_UPLOAD)}. Попробуйте сначала сжать файл")
    file_ids: list[str] = []
    if len(files) == 1:
        msg = await bot.send_document(job.chat_id, FSInputFile(files[0]), caption=caption)
        return [msg.document.file_id]
    for i in range(0, len(files), 10):  # альбомы по 10 файлов
        chunk = files[i:i + 10]
        is_last_chunk = i + 10 >= len(files)
        media = [InputMediaDocument(media=FSInputFile(f),
                                    caption=caption if is_last_chunk and n == len(chunk) - 1 else None)
                 for n, f in enumerate(chunk)]
        msgs = await bot.send_media_group(job.chat_id, media)
        file_ids += [m.document.file_id for m in msgs if m.document]
    return file_ids


async def process_job(ctx: dict, job_id: int) -> None:
    bot: Bot = ctx["bot"]
    job = db.get_job(job_id)
    if not job or job.status != "queued":
        return
    label = op_label(job.op, job.params)
    db.mark_running(job_id)
    await edit_status(bot, job, f"⚙️ {label}\n<b>{escape(job.input_name or '')}</b>\n\nОбрабатываю…")

    workdir = WORK_DIR / f"job_{job_id}"
    started = time.monotonic()
    try:
        uploads = db.get_uploads(job.upload_ids)
        if not uploads:
            raise UserError("Исходный файл не найден — пришлите его ещё раз")
        inputs = []
        for i, up in enumerate(uploads):
            dest = workdir / "in" / f"{i:02d}" / safe_name(up.file_name)
            await download(bot, up.file_id, dest)
            inputs.append((dest, up.kind))

        result = await asyncio.to_thread(process, job.op, job.params, inputs, workdir)
        elapsed = time.monotonic() - started
        notes = f"\n💡 {escape(result.note)}" if result.note else ""

        if result.files == [inputs[0][0]] and job.op == "compress":  # сжать не получилось
            db.mark_done(job_id, "", 0, [])
            await edit_status(bot, job, f"ℹ️ {label}\n<b>{escape(job.input_name or '')}</b>{notes}")
            return

        if result.text:
            await bot.send_message(
                job.chat_id, f"📝 <b>Текст из {escape(job.input_name or 'файла')}:</b>\n"
                             f"<blockquote expandable>{_escape_trim(result.text, 3700)}</blockquote>")

        total = sum(f.stat().st_size for f in result.files)
        name = result.files[0].name if len(result.files) == 1 else f"{len(result.files)} файлов"
        caption = f"✅ {escape(name)} · {human_size(total)}"
        file_ids = await send_results(bot, job, result.files, caption)
        db.mark_done(job_id, name, total, file_ids)
        sizes = f"{human_size(job.input_size)} → {human_size(total)}"
        await edit_status(bot, job, f"✅ {label} · {elapsed:.1f} с\n<b>{escape(job.input_name or '')}</b>\n"
                                    f"{sizes}{notes}")
    except UserError as e:
        db.mark_error(job_id, str(e))
        await edit_status(bot, job, f"❌ {label}\n<b>{escape(job.input_name or '')}</b>\n\n{escape(str(e))}")
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        db.mark_error(job_id, f"{type(e).__name__}: {e}")
        await edit_status(bot, job, f"❌ {label}\n<b>{escape(job.input_name or '')}</b>\n\n"
                                    "Не удалось обработать файл. Возможно, он повреждён или формат "
                                    "не поддерживается для этого действия.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_db()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ctx["bot"] = make_bot()
    for job in db.reset_stuck_jobs():
        await edit_status(ctx["bot"], job, f"❌ {op_label(job.op, job.params)}\n\n"
                                           "Сервер перезапустился во время обработки — отправьте файл ещё раз.")


async def shutdown(ctx: dict) -> None:
    await ctx["bot"].session.close()


class WorkerSettings:
    functions = [func(process_job, timeout=JOB_TIMEOUT, max_tries=1)]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    max_jobs = WORKER_CONCURRENCY
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 3600
