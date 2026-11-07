"""Сквозной сценарий: настоящий диспетчер aiogram + очередь arq/Redis + воркер,
вместо серверов Telegram — фейковый Bot API на aiohttp. Запускается из test_e2e.py."""
import asyncio
import itertools
import json
import os
import sys
import tempfile
from pathlib import Path

from aiohttp import web

PORT = int(os.environ["FAKE_API_PORT"])
SAMPLES = json.loads(os.environ["SAMPLES"])
calls: list[tuple[str, dict]] = []
files: dict[str, str] = {}
counter = itertools.count(1000)
upload_dir = Path(tempfile.mkdtemp())


def msg(chat_id=1, **extra):
    return {"message_id": next(counter), "date": 0, "chat": {"id": int(chat_id), "type": "private"}, **extra}


async def api(request: web.Request) -> web.Response:
    method = request.match_info["method"]
    if request.content_type == "multipart/form-data":
        data = {}
        reader = await request.multipart()
        async for part in reader:
            if part.filename:
                dst = upload_dir / part.filename
                dst.write_bytes(await part.read())
                data[part.name] = str(dst)
            else:
                data[part.name] = (await part.read()).decode()
    elif request.content_type == "application/json":
        data = await request.json()
    else:
        data = dict(await request.post())
    calls.append((method, data))
    chat = data.get("chat_id", 1)
    if method == "getMe":
        return web.json_response({"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "FM",
                                                         "username": "fm_bot"}})
    if method == "getFile":
        path = files[data["file_id"]]
        return web.json_response({"ok": True, "result": {"file_id": data["file_id"], "file_unique_id": "u",
                                                         "file_size": os.path.getsize(path), "file_path": path}})
    if method == "sendDocument":
        doc = data["document"]
        if doc.startswith("attach://"):
            doc = data[doc.removeprefix("attach://")]
        if os.path.exists(doc):
            fid = f"res_{next(counter)}"
            files[fid] = doc
            data["document"] = doc
        else:
            fid = doc
        return web.json_response({"ok": True, "result": msg(chat, document={
            "file_id": fid, "file_unique_id": fid, "file_name": Path(files.get(fid, fid)).name})})
    if method == "sendMediaGroup":
        media = json.loads(data["media"])
        result = []
        for m in media:
            ref = m["media"]
            path = data.get(ref.removeprefix("attach://"), ref)
            fid = f"res_{next(counter)}"
            files[fid] = path
            result.append(msg(chat, document={"file_id": fid, "file_unique_id": fid,
                                              "file_name": Path(path).name}))
        return web.json_response({"ok": True, "result": result})
    if method in ("sendMessage", "editMessageText"):
        return web.json_response({"ok": True, "result": msg(chat, text=data.get("text", ""))})
    return web.json_response({"ok": True, "result": True})


uid = itertools.count(1)


def user_msg(**content):
    n = next(uid)
    return {"update_id": n, "message": {"message_id": n, "date": 0, "chat": {"id": 7, "type": "private"},
                                        "from": {"id": 7, "is_bot": False, "first_name": "Аня"}, **content}}


def doc(sample: str, name: str | None = None, size: int | None = None):
    path = SAMPLES[sample]
    fid = f"in_{sample}_{next(counter)}"
    files[fid] = path
    return {"document": {"file_id": fid, "file_unique_id": fid, "file_name": name or Path(path).name,
                         "file_size": size or os.path.getsize(path)}}


def callback(data: str, message_id: int = 555):
    n = next(uid)
    return {"update_id": n, "callback_query": {
        "id": str(n), "chat_instance": "c", "data": data, "from": {"id": 7, "is_bot": False, "first_name": "Аня"},
        "message": {"message_id": message_id, "date": 0, "chat": {"id": 7, "type": "private"}, "text": "x"}}}


def last(method: str) -> dict:
    return next(d for m, d in reversed(calls) if m == method)


def buttons(data: dict) -> list[str]:
    markup = data.get("reply_markup")
    markup = json.loads(markup) if isinstance(markup, str) else markup or {}
    return [b["callback_data"] for row in markup.get("inline_keyboard", []) for b in row]


async def main() -> None:
    runner = web.AppRunner(web.Application())
    runner.app.router.add_post("/bot{token}/{method}", api)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()

    from aiogram import Dispatcher
    from aiogram.fsm.storage.redis import RedisStorage
    from aiogram.types import Update
    from arq import create_pool
    from arq.worker import create_worker

    from app import db
    from app.bot.handlers import router
    from app.config import REDIS_URL
    from app.telegram import make_bot
    from app.worker import WorkerSettings

    db.init_db()
    bot = make_bot()
    dp = Dispatcher(storage=RedisStorage.from_url(REDIS_URL))
    dp["arq"] = pool = await create_pool(WorkerSettings.redis_settings)
    dp.include_router(router)

    async def feed(*updates):
        for u in updates:
            await dp.feed_update(bot, Update.model_validate(u, context={"bot": bot}))

    async def run_worker():
        w = create_worker(WorkerSettings, burst=True, poll_delay=0.1)
        await w.main()
        await w.close()

    ok = True

    def check(cond, title):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + title)
        ok &= bool(cond)

    # 1. Конвертация DOCX → PDF
    await feed(user_msg(text="/start"), user_msg(**doc("docx")))
    menu = last("sendMessage")
    check("a:1:convert" in buttons(menu), "меню действий для DOCX")
    await feed(callback("a:1:convert"))
    check("c:1:pdf" in buttons(last("editMessageText")), "выбор формата")
    await feed(callback("c:1:pdf"))
    check("⏳" in last("editMessageText")["text"], "задача в очереди")
    await run_worker()
    sent = last("sendDocument")
    check(sent["document"].endswith(".pdf") and Path(sent["document"]).read_bytes()[:4] == b"%PDF",
          "получен PDF")
    check("✅" in last("editMessageText")["text"], "статус «готово»")

    # 2. Текст с картинки (OCR)
    await feed(user_msg(**doc("png")), callback("a:2:text"))
    await run_worker()
    texts = [d["text"] for m, d in calls if m == "sendMessage" and "blockquote" in d.get("text", "")]
    check(texts and "привет" in texts[-1].lower(), "распознан текст с картинки")

    # 3. Объединение PDF + картинка + DOCX
    await feed(user_msg(text="/merge"), user_msg(**doc("pdf")), user_msg(**doc("png")), user_msg(**doc("docx")))
    check("m:go" in buttons(last("sendMessage")), "кнопка «Объединить»")
    await feed(callback("m:go"))
    await run_worker()
    from pypdf import PdfReader

    merged = last("sendDocument")["document"]
    check(merged.endswith("merged.pdf") and len(PdfReader(merged).pages) == 3, "объединённый PDF из 3 страниц")

    # 4. Распаковка ZIP с русскими именами → альбом файлов
    # id загрузок идут по порядку: docx=1, png=2, pdf=3, png=4, docx=5, zip=6, mp4=7, wav=8
    await feed(user_msg(**doc("zip")))
    up_id = 6
    check("a:6:extract" in buttons(last("sendMessage")), "меню архива")
    await feed(callback(f"a:{up_id}:extract"))
    await run_worker()
    group = last("sendMediaGroup")
    check(len(json.loads(group["media"])) == 2, "архив распакован (2 файла альбомом)")

    # 5. Сжатие видео и конвертация аудио
    await feed(user_msg(**doc("mp4")))
    up_id += 1
    await feed(callback(f"c:{up_id}:mp3"))
    await run_worker()
    check(last("sendDocument")["document"].endswith(".mp3"), "видео → MP3")

    # 6. Недопустимый формат (аудио → MP4) отклоняется
    await feed(user_msg(**doc("wav")))
    up_id += 1
    await feed(callback(f"a:{up_id}:convert"))
    await feed(callback(f"c:{up_id}:mp4"))  # недопустимый формат для аудио
    check(last("answerCallbackQuery").get("show_alert"), "недопустимый формат отклонён")

    # 7. Слишком большой файл
    await feed(user_msg(**doc("png", size=5 * 1024 * 1024 * 1024)))
    check("лимита" in last("sendMessage")["text"], "предупреждение о размере")

    # 8. Чужой файл недоступен
    n = next(uid)
    await feed({"update_id": n, "callback_query": {"id": "x", "chat_instance": "c", "data": "c:1:odt",
                                                   "from": {"id": 999, "is_bot": False, "first_name": "Чужой"},
                                                   "message": {"message_id": 1, "date": 0,
                                                               "chat": {"id": 999, "type": "private"}}}})
    check(last("answerCallbackQuery").get("show_alert"), "чужой файл недоступен")

    # 9. История и повторная отправка
    await feed(user_msg(text="🕘 История"))
    hist = last("sendMessage")
    check("История" in hist["text"] and any(b.startswith("h:") for b in buttons(hist)), "история с кнопками")
    first_job = next(b for b in buttons(hist) if b == "h:1")
    await feed(callback(first_job))
    check(last("sendDocument")["document"].startswith("res_"), "повторная отправка по file_id из истории")

    print("JOBS:", db.stats())
    await pool.close()
    await bot.session.close()
    await runner.cleanup()
    sys.exit(0 if ok else 1)


asyncio.run(main())
