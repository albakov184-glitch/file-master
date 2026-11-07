import asyncio
import mimetypes
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InputMediaDocument, Message
from arq import ArqRedis

from app import db
from app.bot import keyboards as kb
from app.config import ADMIN_IDS, MAX_ACTIVE_JOBS_PER_USER, MAX_DOWNLOAD, MAX_MERGE_FILES, TIMEZONE, human_size
from app.formats import KIND_LABELS, MERGEABLE_KINDS, all_formats_text, ext_of, kind_of, op_label, targets_for

router = Router()
TZ = ZoneInfo(TIMEZONE)
_user_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)  # альбомы приходят пачкой


class Merge(StatesGroup):
    collecting = State()


HELP = (
    "🗂 <b>File Master</b> — универсальный бот для файлов\n\n"
    "Просто пришлите файл (документ, фото, видео, аудио, архив…) и выберите действие:\n"
    "• 🔄 <b>Конвертация</b> — 200+ форматов: изображения, документы, таблицы, презентации, "
    "PDF, электронные книги, аудио, видео, архивы, шрифты, субтитры\n"
    "• 🗜 <b>Сжатие</b> — фото, PDF, видео, аудио, любые файлы в ZIP\n"
    "• 📝 <b>Извлечение текста</b> — из документов, PDF и даже фото/сканов (распознавание)\n"
    "• 📎 <b>Объединение в PDF</b> — PDF, картинки и документы в один файл\n"
    "• ✂️ <b>Разделение PDF</b> по страницам\n"
    "• 📂 <b>Распаковка архивов</b> — ZIP, RAR, 7Z, TAR и др.\n"
    "• 🕘 <b>История</b> — все обработанные файлы можно скачать повторно\n\n"
    f"Максимальный размер файла: <b>{human_size(MAX_DOWNLOAD)}</b>\n"
    "💡 Чтобы фото не сжималось, отправляйте его как файл."
)


# ---------- извлечение файла из сообщения ----------
def file_from_message(m: Message) -> tuple[str, str, int | None] | None:
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")

    def with_ext(name: str | None, mime: str | None, default: str) -> str:
        if name and ext_of(name):
            return name
        ext = (mimetypes.guess_extension(mime or "") or f".{default}").lstrip(".")
        ext = {"jpe": "jpg", "oga": "ogg"}.get(ext, ext)
        return f"{name or default + '_' + stamp}.{ext}" if name else f"{default}_{stamp}.{ext}"

    if m.document:
        d = m.document
        return d.file_id, with_ext(d.file_name, d.mime_type, "file"), d.file_size
    if m.photo:
        p = m.photo[-1]
        return p.file_id, f"photo_{stamp}.jpg", p.file_size
    if m.video:
        return m.video.file_id, with_ext(m.video.file_name, m.video.mime_type, "video"), m.video.file_size
    if m.audio:
        return m.audio.file_id, with_ext(m.audio.file_name, m.audio.mime_type, "audio"), m.audio.file_size
    if m.voice:
        return m.voice.file_id, f"voice_{stamp}.ogg", m.voice.file_size
    if m.video_note:
        return m.video_note.file_id, f"video_note_{stamp}.mp4", m.video_note.file_size
    if m.animation:
        a = m.animation
        return a.file_id, with_ext(a.file_name, a.mime_type, "animation"), a.file_size
    if m.sticker:
        s = m.sticker
        ext = "tgs" if s.is_animated else "webm" if s.is_video else "webp"
        return s.file_id, f"sticker_{stamp}.{ext}", s.file_size
    return None


FILE_FILTER = F.document | F.photo | F.video | F.audio | F.voice | F.video_note | F.animation | F.sticker


# ---------- команды ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(f"Привет, {escape(message.from_user.first_name)}! 👋\n\n{HELP}",
                         reply_markup=kb.main_menu())


@router.message(Command("help"))
@router.message(F.text == kb.BTN_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=kb.main_menu())


@router.message(Command("formats"))
@router.message(F.text == kb.BTN_FORMATS)
async def cmd_formats(message: Message) -> None:
    await message.answer("📋 <b>Поддерживаемые форматы</b>\n\n" + all_formats_text())


@router.message(Command("stats"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stats(message: Message) -> None:
    s = db.stats()
    await message.answer(f"📊 Задач: {s['jobs']} · пользователей: {s['users']}\n"
                         f"✅ {s['done']} · ❌ {s['errors']} · ⏳ в работе {s['active']}")


@router.message(Command("history"))
@router.message(F.text == kb.BTN_HISTORY)
async def cmd_history(message: Message) -> None:
    jobs = db.history(message.from_user.id)
    if not jobs:
        await message.answer("История пуста — пришлите первый файл 🙂")
        return
    icons = {"queued": "⏳", "running": "⚙️", "done": "✅", "error": "❌"}
    lines = []
    for j in jobs:
        when = datetime.fromisoformat(j.created_at).replace(tzinfo=timezone.utc).astimezone(TZ)
        line = f"{icons[j.status]} <b>#{j.id}</b> · {when:%d.%m %H:%M} · {op_label(j.op, j.params)}\n" \
               f"    {escape(j.input_name or '')} ({human_size(j.input_size)})"
        if j.status == "done" and j.result_name:
            line += f" → {escape(j.result_name)} ({human_size(j.result_size)})"
        elif j.status == "error" and j.error:
            line += f"\n    <i>{escape(j.error[:120])}</i>"
        lines.append(line)
    await message.answer("🕘 <b>История</b>\n\n" + "\n\n".join(lines), reply_markup=kb.history_kb(jobs))


@router.callback_query(F.data.startswith("h:"))
async def cb_history_file(call: CallbackQuery) -> None:
    job = db.get_job(int(call.data[2:]))
    if not job or job.user_id != call.from_user.id or not job.result_file_ids:
        await call.answer("Файл недоступен", show_alert=True)
        return
    ids = job.result_file_ids
    if len(ids) == 1:
        await call.message.answer_document(ids[0], caption=f"🕘 #{job.id} · {escape(job.result_name or '')}")
    else:
        for i in range(0, len(ids), 10):
            await call.message.answer_media_group([InputMediaDocument(media=x) for x in ids[i:i + 10]])
    await call.answer()


# ---------- объединение ----------
@router.message(F.text == kb.BTN_MERGE)
@router.message(Command("merge"))
async def merge_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Merge.collecting)
    await state.update_data(ids=[])
    await message.answer("📎 <b>Объединение в PDF</b>\n\nПришлите по очереди файлы: PDF, картинки, документы, "
                         "таблицы, презентации. Порядок сохранится.", reply_markup=kb.merge_kb(0))


@router.message(Merge.collecting, FILE_FILTER)
async def merge_add(message: Message, state: FSMContext) -> None:
    info = file_from_message(message)
    async with _user_locks[message.from_user.id]:
        file_id, name, size = info
        ext = ext_of(name)
        kind = kind_of(ext)
        if kind not in MERGEABLE_KINDS:
            await message.reply(f"⚠️ {escape(name)} нельзя добавить в PDF — пропускаю")
            return
        if size and size > MAX_DOWNLOAD:
            await message.reply(f"⚠️ {escape(name)} больше {human_size(MAX_DOWNLOAD)} — пропускаю")
            return
        ids = (await state.get_data()).get("ids", [])
        if len(ids) >= MAX_MERGE_FILES:
            await message.reply(f"Максимум {MAX_MERGE_FILES} файлов")
            return
        ids.append(db.add_upload(message.from_user.id, file_id, name, ext, kind, size))
        await state.update_data(ids=ids)
    await message.reply(f"➕ {escape(name)} — файлов: {len(ids)}", reply_markup=kb.merge_kb(len(ids)))


@router.callback_query(F.data == "m:cancel")
async def merge_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Объединение отменено")
    await call.answer()


@router.callback_query(F.data == "m:go")
async def merge_go(call: CallbackQuery, state: FSMContext, arq: ArqRedis) -> None:
    if await state.get_state() != Merge.collecting.state:
        await call.answer("Режим объединения уже завершён", show_alert=True)
        return
    ids = (await state.get_data()).get("ids", [])
    if len(ids) < 2:
        await call.answer("Нужно минимум 2 файла", show_alert=True)
        return
    uploads = db.get_uploads(ids)
    if await enqueue(call, arq, "merge", {}, uploads):
        await state.clear()


# ---------- приём файла ----------
@router.message(FILE_FILTER)
async def on_file(message: Message) -> None:
    file_id, name, size = file_from_message(message)
    if size and size > MAX_DOWNLOAD:
        await message.reply(f"⚠️ Файл {human_size(size)} — больше лимита {human_size(MAX_DOWNLOAD)}.\n"
                            "Это ограничение Telegram для ботов.")
        return
    ext = ext_of(name)
    kind = kind_of(ext)
    up = db.get_upload(db.add_upload(message.from_user.id, file_id, name, ext, kind, size))
    await message.reply(f"{KIND_LABELS[kind]}: <b>{escape(name)}</b> · {human_size(size)}\n\nЧто сделать?",
                        reply_markup=kb.actions_kb(up))


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message) -> None:
    await message.answer("Пришлите файл — и я предложу, что с ним можно сделать 📎", reply_markup=kb.main_menu())


# ---------- действия ----------
def _own_upload(call: CallbackQuery, upload_id: str) -> db.Upload | None:
    up = db.get_upload(int(upload_id))
    return up if up and up.user_id == call.from_user.id else None


async def enqueue(call: CallbackQuery, arq: ArqRedis, op: str, params: dict, uploads: list[db.Upload]) -> bool:
    if db.active_jobs(call.from_user.id) >= MAX_ACTIVE_JOBS_PER_USER:
        await call.answer(f"У вас уже {MAX_ACTIVE_JOBS_PER_USER} задачи в работе — дождитесь их завершения",
                          show_alert=True)
        return False
    job_id = db.create_job(call.from_user.id, call.message.chat.id, op, params, uploads)
    pos = db.queue_position(job_id)
    name = uploads[0].file_name if len(uploads) == 1 else f"{len(uploads)} файлов"
    wait = f"В очереди: {pos}-й" if pos > 1 else "Скоро начну…"
    await call.message.edit_text(f"⏳ {op_label(op, params)}\n<b>{escape(name)}</b>\n\n{wait}")
    db.set_status_msg(job_id, call.message.message_id)
    await arq.enqueue_job("process_job", job_id, _job_id=f"job-{job_id}")
    await call.answer()
    return True


@router.callback_query(F.data.startswith("a:"))
async def cb_action(call: CallbackQuery, state: FSMContext, arq: ArqRedis) -> None:
    _, upload_id, act = call.data.split(":")
    up = _own_upload(call, upload_id)
    if not up:
        await call.answer("Файл не найден — пришлите его ещё раз", show_alert=True)
        return
    if act == "convert":
        await call.message.edit_text(f"🔄 <b>{escape(up.file_name)}</b>\nВ какой формат?",
                                     reply_markup=kb.targets_kb(up))
        await call.answer()
        return
    if act == "merge":
        await state.set_state(Merge.collecting)
        await state.update_data(ids=[up.id])
        await call.message.edit_text(f"📎 <b>Объединение в PDF</b>\n\n1. {escape(up.file_name)}\n\n"
                                     "Пришлите остальные файлы, затем нажмите «Объединить».",
                                     reply_markup=kb.merge_kb(1))
        await call.answer()
        return
    await enqueue(call, arq, act, {}, [up])


@router.callback_query(F.data.startswith("c:"))
async def cb_convert(call: CallbackQuery, arq: ArqRedis) -> None:
    _, upload_id, target = call.data.split(":", 2)
    up = _own_upload(call, upload_id)
    if not up or target not in targets_for(up.kind, up.ext):
        await call.answer("Файл не найден — пришлите его ещё раз", show_alert=True)
        return
    await enqueue(call, arq, "convert", {"target": target}, [up])


@router.callback_query(F.data.startswith("b:"))
async def cb_back(call: CallbackQuery) -> None:
    up = _own_upload(call, call.data[2:])
    if not up:
        await call.answer("Файл не найден", show_alert=True)
        return
    await call.message.edit_text(f"{KIND_LABELS[up.kind]}: <b>{escape(up.file_name)}</b> · {human_size(up.size)}"
                                 "\n\nЧто сделать?", reply_markup=kb.actions_kb(up))
    await call.answer()
