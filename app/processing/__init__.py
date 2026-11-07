"""Единая точка входа обработки: process(op, params, inputs, workdir) -> Result.
Синхронный код — воркер вызывает его в отдельном потоке."""
from pathlib import Path

from app.config import MAX_MERGE_FILES
from app.formats import MERGEABLE_KINDS
from app.processing import archives, images, media, misc, office, pdf
from app.processing.common import Result, UserError, out_path, read_text_file

TEXT_PREVIEW = 3500


def _text_result(text: str, src: Path, workdir: Path) -> Result:
    text = (text or "").strip()
    if not text:
        raise UserError("Текст не найден. Если это скан или фото — попробуйте более чёткое изображение")
    dst = out_path(workdir, src, "txt", "_text")
    dst.write_text(text, encoding="utf-8")
    preview = text if len(text) <= TEXT_PREVIEW else text[:TEXT_PREVIEW] + "…"
    return Result([dst], text=preview, note=f"Символов: {len(text)}")


def convert(src: Path, kind: str, target: str, workdir: Path) -> Result:
    if kind == "image":
        return images.convert(src, target, workdir)
    if kind in ("audio", "video"):
        return media.convert(src, target, workdir)
    if kind == "subtitle":
        return media.convert_subtitles(src, target, workdir)
    if kind == "archive":
        return archives.convert(src, target, workdir)
    if kind == "font":
        return misc.convert_font(src, target, workdir)
    if kind in ("pdf", "doc", "sheet", "slides", "markup", "ebook", "text"):
        return office.convert(src, kind, target, workdir)
    raise UserError("Этот тип файлов нельзя конвертировать — только упаковать в ZIP")


def extract_text(src: Path, kind: str, workdir: Path) -> Result:
    if kind == "image":
        text = images.extract_text(src, workdir)
    elif kind == "pdf":
        text = pdf.extract_text(src, workdir)
    elif kind == "subtitle":
        text = read_text_file(src)
    elif kind in ("doc", "sheet", "slides", "markup", "ebook", "text"):
        text = office.extract_text(src, kind, workdir)
    else:
        raise UserError("Из этого типа файлов текст не извлекается")
    return _text_result(text, src, workdir)


def compress(src: Path, kind: str, workdir: Path) -> Result:
    if kind == "image":
        return images.compress(src, workdir)
    if kind == "pdf":
        return pdf.compress(src, workdir)
    if kind in ("audio", "video"):
        return media.compress(src, workdir)
    return archives.zip_file(src, workdir)


def merge(inputs: list[tuple[Path, str]], workdir: Path) -> Result:
    if len(inputs) < 2:
        raise UserError("Для объединения нужно минимум 2 файла")
    if len(inputs) > MAX_MERGE_FILES:
        raise UserError(f"Можно объединить не больше {MAX_MERGE_FILES} файлов")
    pdfs = []
    for src, kind in inputs:
        if kind not in MERGEABLE_KINDS:
            raise UserError(f"Файл {src.name} нельзя добавить в PDF")
        pdfs.append(office.to_pdf(src, kind, workdir))
    return Result([pdf.merge(pdfs, workdir, name="merged")], note=f"Объединено файлов: {len(inputs)}")


def process(op: str, params: dict, inputs: list[tuple[Path, str]], workdir: Path) -> Result:
    if op == "merge":
        return merge(inputs, workdir)
    src, kind = inputs[0]
    if op == "convert":
        return convert(src, kind, params["target"], workdir)
    if op == "compress":
        return compress(src, kind, workdir)
    if op == "zip":
        return archives.zip_file(src, workdir)
    if op == "text":
        return extract_text(src, kind, workdir)
    if op == "split":
        return pdf.split(src, workdir)
    if op == "extract":
        return archives.extract(src, workdir)
    raise UserError("Неизвестное действие")
