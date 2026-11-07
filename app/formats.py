"""Реестр форматов: что за файл и что с ним можно сделать."""
import shutil
from pathlib import Path

HAS_CALIBRE = shutil.which("ebook-convert") is not None

KINDS: dict[str, set[str]] = {
    "image": {"jpg", "jpeg", "jfif", "png", "webp", "gif", "bmp", "tiff", "tif", "ico", "heic", "heif",
              "avif", "svg", "psd", "tga", "ppm", "pgm", "pbm", "pcx", "xcf", "eps", "jp2", "dds", "icns"},
    "pdf": {"pdf"},
    "doc": {"doc", "docx", "docm", "dot", "dotx", "odt", "fodt", "ott", "rtf", "wpd", "wps", "sxw", "pages",
            "abw", "lwp", "hwp", "txt"},
    "sheet": {"xls", "xlsx", "xlsm", "xlsb", "ods", "fods", "csv", "tsv", "numbers", "sxc", "dbf", "123"},
    "slides": {"ppt", "pptx", "pptm", "pps", "ppsx", "odp", "fodp", "key", "sxi"},
    "markup": {"md", "markdown", "html", "htm", "xhtml", "epub", "fb2", "rst", "tex", "latex", "org",
               "ipynb", "textile", "opml", "typ", "dbk", "man"},
    "ebook": {"mobi", "azw", "azw3", "azw4", "lit", "pdb", "lrf", "prc", "tcr", "snb", "cbz", "cbr", "djvu"},
    "audio": {"mp3", "wav", "ogg", "oga", "opus", "flac", "m4a", "aac", "wma", "amr", "aiff", "aif", "ape",
              "mka", "ac3", "wv", "caf", "m4b", "mp2", "spx", "au", "dts", "tta"},
    "video": {"mp4", "mkv", "avi", "mov", "webm", "wmv", "flv", "3gp", "3g2", "m4v", "mpeg", "mpg", "ts",
              "mts", "m2ts", "vob", "ogv", "f4v", "asf", "rm", "rmvb", "divx", "mxf", "y4m"},
    "archive": {"zip", "7z", "rar", "tar", "gz", "tgz", "bz2", "tbz", "tbz2", "xz", "txz", "lzma", "zst",
                "iso", "cab", "arj", "lzh", "z", "cpio", "rpm", "deb", "jar", "apk", "wim"},
    "font": {"ttf", "otf", "woff", "woff2"},
    "subtitle": {"srt", "vtt", "ass", "ssa", "sub", "sbv"},
    "text": {"json", "xml", "yaml", "yml", "log", "ini", "cfg", "conf", "toml", "py", "js", "ts", "jsx", "tsx",
             "java", "c", "cpp", "h", "hpp", "cs", "go", "rs", "php", "rb", "swift", "kt", "sql", "sh", "bat",
             "ps1", "css", "scss", "lua", "pl", "r", "dart", "vue", "env", "properties"},
}
# «ts» встречается и в видео, и в коде — считаем видео (MPEG-TS)
KINDS["text"].discard("ts")

KIND_LABELS = {
    "image": "🖼 Изображение", "pdf": "📕 PDF", "doc": "📄 Документ", "sheet": "📊 Таблица",
    "slides": "📽 Презентация", "markup": "📝 Текст/разметка", "ebook": "📚 Эл. книга", "audio": "🎵 Аудио",
    "video": "🎬 Видео", "archive": "🗜 Архив", "font": "🔤 Шрифт", "subtitle": "💬 Субтитры",
    "text": "🧾 Текст/код", "other": "📦 Файл",
}

_EBOOK_TARGETS = ["epub", "fb2", "mobi", "azw3", "pdf", "docx", "txt"]

TARGETS: dict[str, list[str]] = {
    "image": ["jpg", "png", "webp", "pdf", "gif", "bmp", "tiff", "ico", "avif", "heic"],
    "pdf": ["docx", "jpg", "png", "txt", "html", "epub"],
    "doc": ["pdf", "docx", "doc", "odt", "rtf", "txt", "html", "epub", "fb2", "md"],
    "sheet": ["pdf", "xlsx", "xls", "ods", "csv", "html"],
    "slides": ["pdf", "pptx", "ppt", "odp", "png", "jpg"],
    "markup": ["pdf", "docx", "odt", "html", "md", "epub", "fb2", "txt", "rtf"]
              + (["mobi", "azw3"] if HAS_CALIBRE else []),
    "ebook": _EBOOK_TARGETS if HAS_CALIBRE else [],
    "audio": ["mp3", "wav", "ogg", "opus", "flac", "m4a", "aac", "wma", "aiff"],
    "video": ["mp4", "mkv", "avi", "mov", "webm", "gif", "mp3", "m4a", "wav"],
    "archive": ["zip", "7z", "tar.gz"],
    "font": ["ttf", "otf", "woff", "woff2"],
    "subtitle": ["srt", "vtt", "ass"],
    "text": ["pdf", "docx", "txt"],
    "other": [],
}

# Действия помимо конвертации
ACTIONS: dict[str, list[str]] = {
    "image": ["compress", "text", "merge"],
    "pdf": ["compress", "text", "split", "merge"],
    "doc": ["text", "merge", "zip"],
    "sheet": ["text", "merge", "zip"],
    "slides": ["text", "merge", "zip"],
    "markup": ["text", "merge", "zip"],
    "ebook": ["text", "zip"] if HAS_CALIBRE else ["zip"],
    "audio": ["compress"],
    "video": ["compress"],
    "archive": ["extract"],
    "font": ["zip"],
    "subtitle": ["text"],
    "text": ["text", "merge", "zip"],
    "other": ["zip"],
}

ACTION_LABELS = {
    "convert": "🔄 Конвертировать",
    "compress": "🗜 Сжать",
    "zip": "🗜 Упаковать в ZIP",
    "text": "📝 Извлечь текст",
    "split": "✂️ Разделить по страницам",
    "merge": "📎 Объединить с другими в PDF",
    "extract": "📂 Распаковать",
}

MERGEABLE_KINDS = {"pdf", "image", "doc", "sheet", "slides", "markup", "text"}


def ext_of(filename: str) -> str:
    name = filename.lower()
    for double in ("tar.gz", "tar.bz2", "tar.xz"):
        if name.endswith("." + double):
            return double
    return Path(name).suffix.lstrip(".")


def kind_of(ext: str) -> str:
    if ext in ("tar.gz", "tar.bz2", "tar.xz"):
        return "archive"
    for kind, exts in KINDS.items():
        if ext in exts:
            return kind
    return "other"


def targets_for(kind: str, ext: str) -> list[str]:
    same = {ext, {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff", "htm": "html", "markdown": "md",
                  "aif": "aiff", "oga": "ogg"}.get(ext, ext)}
    if kind == "archive":
        same.add({"tgz": "tar.gz"}.get(ext, ext))
    return [t for t in TARGETS.get(kind, []) if t not in same]


def actions_for(kind: str) -> list[str]:
    acts = list(ACTIONS.get(kind, ["zip"]))
    return (["convert"] if TARGETS.get(kind) else []) + acts


def all_formats_text() -> str:
    lines = []
    for kind, exts in KINDS.items():
        targets = TARGETS.get(kind) or []
        lines.append(
            f"<b>{KIND_LABELS[kind]}</b>: {', '.join(sorted(exts))}"
            + (f"\n   → {', '.join(targets)}" if targets else "")
        )
    lines.append(f"<b>{KIND_LABELS['other']}</b>: любой другой — упаковка в ZIP")
    return "\n\n".join(lines)


def op_label(op: str, params: dict | None = None) -> str:
    params = params or {}
    return {
        "convert": f"Конвертация → {params.get('target', '').upper()}",
        "compress": "Сжатие",
        "zip": "Упаковка в ZIP",
        "text": "Извлечение текста",
        "split": "Разделение PDF",
        "extract": "Распаковка архива",
        "merge": "Объединение в PDF",
    }.get(op, op)
