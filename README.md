# 🗂 File Master

Универсальный Telegram-бот для работы с файлами: конвертация 200+ форматов, сжатие, объединение и
разделение PDF, извлечение текста (включая распознавание сканов и фото), распаковка архивов и история
обработанных файлов. Тяжёлая обработка идёт в фоне через очередь задач.

Всё построено на бесплатных open-source инструментах — платить ни за какие API не нужно.

**🌐 Сайт с живым демо:** https://albakov184-glitch.github.io/file-master/

## Возможности

| Что | Форматы |
|---|---|
| 🖼 **Изображения** | JPG, PNG, WEBP, HEIC (iPhone), AVIF, GIF (с анимацией), BMP, TIFF, ICO, SVG, PSD, EPS… → JPG, PNG, WEBP, PDF, GIF, BMP, TIFF, ICO, AVIF, HEIC |
| 📄 **Документы** | DOC, DOCX, ODT, RTF, TXT, WPD, Pages… → PDF, DOCX, DOC, ODT, RTF, TXT, HTML, EPUB, FB2, MD |
| 📊 **Таблицы** | XLS, XLSX, ODS, CSV, Numbers… → PDF, XLSX, XLS, ODS, CSV, HTML |
| 📽 **Презентации** | PPT, PPTX, ODP, Keynote… → PDF, PPTX, PPT, ODP, PNG/JPG (по слайдам) |
| 📕 **PDF** | → DOCX, JPG/PNG (по страницам), TXT, HTML, EPUB; сжатие, разделение, объединение |
| 📝 **Разметка и книги** | MD, HTML, EPUB, FB2, RST, LaTeX, ipynb… → PDF, DOCX, EPUB, FB2, MOBI, AZW3… |
| 📚 **Эл. книги** | MOBI, AZW3, DJVU, CBZ, LIT… → EPUB, FB2, PDF, DOCX, TXT (через Calibre) |
| 🎵 **Аудио** | MP3, WAV, OGG, OPUS, FLAC, M4A, AAC, WMA, AMR, голосовые… → MP3, WAV, OGG, OPUS, FLAC, M4A, AAC, WMA, AIFF |
| 🎬 **Видео** | MP4, MKV, AVI, MOV, WEBM, WMV, FLV, 3GP, кружочки… → MP4, MKV, AVI, MOV, WEBM, GIF, MP3 (звук) |
| 🗜 **Архивы** | ZIP, RAR, 7Z, TAR, GZ, BZ2, XZ, ISO… → распаковка, перепаковка в ZIP / 7Z / TAR.GZ |
| 🔤 **Шрифты** | TTF, OTF ↔ WOFF, WOFF2 |
| 💬 **Субтитры** | SRT ↔ VTT ↔ ASS |
| 📦 **Любой другой файл** | упаковка в ZIP |

Плюс:
- **📝 Извлечение текста** из документов, таблиц, презентаций, книг и PDF. Сканы и фото распознаются через Tesseract (русский + английский).
- **📎 Объединение в PDF**: PDF, картинки, документы, таблицы и презентации в один файл, порядок сохраняется.
- **🗜 Сжатие**: фото (с умным выбором формата), PDF (Ghostscript), видео (H.264), аудио, любые файлы в ZIP.
- **🕘 История**: последние операции со статусами. Любой результат можно скачать повторно по кнопке (через `file_id`, без повторной обработки).
- **⏳ Очередь**: пользователь видит «в очереди: 3-й» → «обрабатываю…» → «✅ готово за 2.1 с · 1.2 МБ → 340 КБ».

## Архитектура

```
Telegram ──► bot (aiogram 3) ──► Redis (очередь arq) ──► worker × N
               │  принимает файлы,                        │ скачивает файл, обрабатывает
               │  показывает меню,                        │ (LibreOffice, FFmpeg, Pandoc,
               │  ставит задачи                           │  ImageMagick, Tesseract, 7-Zip…),
               ▼                                          ▼ отправляет результат
            SQLite (загрузки, задачи, история) ◄──────────┘
```

- `app/bot/` — Telegram-бот: приём файлов, меню, режим объединения, история.
- `app/worker.py` — воркер очереди (arq): скачивание, обработка в отдельном потоке, отправка, статусы.
- `app/processing/` — вся работа с файлами, не зависит от Telegram (легко переиспользовать).
- `app/formats.py` — реестр форматов: тип файла → доступные действия и целевые форматы.
- `app/db.py` — SQLite в режиме WAL (бот и воркеры пишут одновременно).

Защита: лимит активных задач на пользователя, таймауты, защита от zip-бомб и путей `../` в архивах,
чужие файлы и задачи недоступны, при перезапуске зависшие задачи помечаются ошибкой.

## Запуск (Docker — рекомендуется)

1. Создайте бота у [@BotFather](https://t.me/BotFather) и получите токен.
2. На сервере с Docker:
   ```bash
   git clone https://github.com/<ваш-аккаунт>/file-master.git && cd file-master
   cp .env.example .env      # впишите BOT_TOKEN
   docker compose up -d --build
   ```
3. Больше параллельной обработки: `docker compose up -d --scale worker=3`.

Логи: `docker compose logs -f bot worker`.

### Бесплатный хостинг

- **Oracle Cloud Always Free**: ARM-сервер до 4 ядер и 24 ГБ RAM бесплатно навсегда. Образ собирается и под ARM.
  При регистрации нужна карта для проверки, деньги не списываются. Ставите Docker и выполняете шаги выше.
- **Свой компьютер**: тоже подходит, бот работает, пока компьютер включён.

### Большие файлы (до 2 ГБ)

Облачный Bot API разрешает ботам скачивать файлы до **20 МБ** и отправлять до **50 МБ**.
Бесплатно снять ограничение можно своим сервером Bot API:
1. Получите `api_id` и `api_hash` на https://my.telegram.org.
2. Впишите их в `.env` и раскомментируйте `BOT_API_URL=http://telegram-bot-api:8081`.
3. `docker compose --profile bigfiles up -d --build`

## Разработка

Без Docker нужны системные пакеты: `libreoffice ffmpeg imagemagick librsvg2-bin ghostscript
tesseract-ocr tesseract-ocr-rus pandoc 7zip redis-server` (и по желанию `calibre djvulibre-bin`).

```bash
pip install -r requirements-dev.txt
cp .env.example .env        # REDIS_URL=redis://localhost:6379
python -m app.bot.main      # бот
arq app.worker.WorkerSettings   # воркер (в отдельном терминале)
```

Тесты:
```bash
python -m pytest -q
```
- `tests/test_processing.py`: 100+ реальных конвертаций на сгенерированных файлах.
- `tests/test_e2e.py`: сквозной сценарий: настоящий бот + Redis + воркер, вместо Telegram фейковый Bot API.

CI (GitHub Actions) собирает Docker-образ и прогоняет все тесты внутри него.
