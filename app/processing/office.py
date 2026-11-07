"""Документы, таблицы, презентации, разметка и электронные книги:
LibreOffice (офисные форматы), Pandoc (разметка), Calibre (эл. книги)."""
import shutil
from pathlib import Path

from app.processing.common import Result, UserError, has, out_path, read_text_file, run, tmp_dir

LO_FILTERS = {
    "txt": "txt:Text (encoded):UTF8",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
}
PANDOC_READERS = {
    "md": "markdown", "markdown": "markdown", "html": "html", "htm": "html", "xhtml": "html",
    "epub": "epub", "fb2": "fb2", "rst": "rst", "tex": "latex", "latex": "latex", "org": "org",
    "ipynb": "ipynb", "textile": "textile", "opml": "opml", "typ": "typst", "dbk": "docbook", "man": "man",
    "docx": "docx", "odt": "odt", "rtf": "rtf",
}
PANDOC_WRITERS = {"md": "gfm", "txt": "plain", "html": "html5", "docx": "docx", "odt": "odt", "epub": "epub3",
                  "fb2": "fb2", "rtf": "rtf"}


def libreoffice(src: Path, fmt: str, workdir: Path) -> Path:
    if not has("soffice"):
        raise UserError("На сервере не установлен LibreOffice")
    outdir = tmp_dir(workdir)
    profile = tmp_dir(workdir)  # отдельный профиль — можно запускать несколько конвертаций параллельно
    run(["soffice", "--headless", "--norestore", "--nolockcheck", f"-env:UserInstallation=file://{profile}",
         "--convert-to", LO_FILTERS.get(fmt, fmt), "--outdir", outdir, src], timeout=300)
    result = outdir / f"{src.stem}.{fmt}"
    if not result.exists():
        raise UserError(f"LibreOffice не смог сконвертировать файл в {fmt.upper()}")
    return result


def pandoc(src: Path, target: str, workdir: Path, reader: str | None = None) -> Path:
    if not has("pandoc"):
        raise UserError("На сервере не установлен Pandoc")
    reader = reader or PANDOC_READERS.get(src.suffix.lower().lstrip("."), "markdown")
    dst = tmp_dir(workdir) / f"{src.stem}.{target}"
    cmd = ["pandoc", "-f", reader, "-t", PANDOC_WRITERS.get(target, target), "-s", "-o", dst, src,
           "--metadata", f"title={src.stem}", "--resource-path", src.parent]
    if target == "html":
        cmd += ["--embed-resources"]
    try:
        run(cmd, timeout=300)
    except RuntimeError:
        if target != "html":
            raise
        run([c for c in cmd if c != "--embed-resources"], timeout=300)
    return dst


def calibre(src: Path, target: str, workdir: Path) -> Path:
    if not has("ebook-convert"):
        raise UserError("Для этого формата нужен Calibre — он есть в Docker-версии бота")
    dst = tmp_dir(workdir) / f"{src.stem}.{target}"
    run(["ebook-convert", src, dst], timeout=600)
    return dst


def _as_plain_text_copy(src: Path, workdir: Path) -> Path:
    """Файлы кода/данных открываем в LibreOffice как обычный текст."""
    dst = tmp_dir(workdir) / f"{src.stem}.txt"
    dst.write_text(read_text_file(src), encoding="utf-8")
    return dst


def _final(path: Path, workdir: Path, src: Path) -> Path:
    dst = out_path(workdir, src, path.suffix.lstrip("."))
    shutil.move(path, dst)
    return dst


def to_docx(src: Path, workdir: Path) -> Path:
    ext = src.suffix.lower().lstrip(".")
    if ext == "docx":
        return src
    if ext == "pdf":
        from pdf2docx import Converter

        dst = tmp_dir(workdir) / f"{src.stem}.docx"
        cv = Converter(str(src))
        try:
            cv.convert(str(dst))
        finally:
            cv.close()
        return dst
    if ext in PANDOC_READERS and ext not in ("odt", "rtf"):
        return pandoc(src, "docx", workdir)
    return libreoffice(src, "docx", workdir)


def to_pdf(src: Path, kind: str, workdir: Path) -> Path:
    """Любой документ → PDF (для объединения и предпросмотра)."""
    if kind == "pdf":
        return src
    if kind == "image":
        from app.processing import images

        return images.convert(src, "pdf", workdir).files[0]
    if kind == "text":
        return libreoffice(_as_plain_text_copy(src, workdir), "pdf", workdir)
    if kind == "markup":
        return libreoffice(pandoc(src, "docx", workdir), "pdf", workdir)
    if kind == "ebook":
        return calibre(src, "pdf", workdir)
    return libreoffice(src, "pdf", workdir)


def convert(src: Path, kind: str, target: str, workdir: Path) -> Result:
    ext = src.suffix.lower().lstrip(".")

    if kind == "ebook":
        if ext == "djvu" and target == "pdf" and has("ddjvu"):
            dst = out_path(workdir, src, "pdf")
            run(["ddjvu", "-format=pdf", src, dst], timeout=600)
            return Result([dst])
        return Result([_final(calibre(src, target, workdir), workdir, src)])

    if kind in ("slides", "pdf") and target in ("png", "jpg"):
        from app.processing import pdf

        return pdf.to_images(to_pdf(src, kind, workdir), target, workdir, name=src.stem)

    if target in ("mobi", "azw3"):
        epub = src if ext == "epub" else pandoc(to_docx(src, workdir) if kind != "markup" else src, "epub",
                                                workdir)
        return Result([_final(calibre(epub, target, workdir), workdir, src)])

    if kind == "text":
        return Result([_final(libreoffice(_as_plain_text_copy(src, workdir), target, workdir), workdir, src)])

    if kind == "markup":
        if target == "pdf":
            return Result([_final(to_pdf(src, kind, workdir), workdir, src)])
        return Result([_final(pandoc(src, target, workdir), workdir, src)])

    if kind == "pdf":
        docx = to_docx(src, workdir)
        if target == "docx":
            return Result([_final(docx, workdir, src)])
        return Result([_final(pandoc(docx, target, workdir), workdir, src)])

    # doc / sheet / slides
    if target in ("epub", "fb2", "md"):
        return Result([_final(pandoc(to_docx(src, workdir), target, workdir), workdir, src)])
    note = "В CSV попадает только первый лист таблицы" if target == "csv" and kind == "sheet" else None
    return Result([_final(libreoffice(src, target, workdir), workdir, src)], note=note)


def extract_text(src: Path, kind: str, workdir: Path) -> str:
    ext = src.suffix.lower().lstrip(".")
    if kind == "text" or ext in ("txt", "csv", "tsv"):
        return read_text_file(src)
    if ext == "docx":
        import docx

        d = docx.Document(str(src))
        parts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    if kind == "markup":
        return read_text_file(pandoc(src, "txt", workdir))
    if kind == "ebook":
        return read_text_file(calibre(src, "txt", workdir))
    if kind == "sheet":
        return read_text_file(libreoffice(src, "csv", workdir))
    if kind == "slides":
        from app.processing import pdf

        return pdf.extract_text(libreoffice(src, "pdf", workdir), workdir)
    return read_text_file(libreoffice(src, "txt", workdir))
