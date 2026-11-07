import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.config import MAX_OCR_PAGES, MAX_PDF_PAGES_RENDER
from app.processing.common import Result, UserError, has, out_path, run, tmp_dir


def _reader(src: Path) -> PdfReader:
    try:
        reader = PdfReader(str(src))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UserError("PDF защищён паролем")
        return reader
    except UserError:
        raise
    except Exception:
        raise UserError("Файл PDF повреждён или не читается") from None


def merge(pdfs: list[Path], workdir: Path, name: str = "merged") -> Path:
    writer = PdfWriter()
    for p in pdfs:
        writer.append(_reader(p))
    dst = workdir / "out" / f"{name}.pdf"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f:
        writer.write(f)
    return dst


def split(src: Path, workdir: Path) -> Result:
    reader = _reader(src)
    n = len(reader.pages)
    if n < 2:
        raise UserError("В PDF всего одна страница — делить нечего")
    dst = out_path(workdir, src, "zip", "_pages")
    width = len(str(n))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, page in enumerate(reader.pages, 1):
            w = PdfWriter()
            w.add_page(page)
            part = tmp_dir(workdir) / f"{src.stem}_{i:0{width}d}.pdf"
            with open(part, "wb") as f:
                w.write(f)
            zf.write(part, part.name)
    return Result([dst], note=f"Страниц: {n}")


def _render(src: Path, scale: float, limit: int):
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(str(src))
    except Exception:
        raise UserError("Файл PDF повреждён, защищён паролем или не читается") from None
    for i in range(min(len(doc), limit)):
        yield i, len(doc), doc[i].render(scale=scale).to_pil()


def to_images(src: Path, fmt: str, workdir: Path, name: str | None = None) -> Result:
    name = name or src.stem
    files = []
    total = 0
    for i, total, img in _render(src, scale=2, limit=MAX_PDF_PAGES_RENDER):
        p = tmp_dir(workdir) / f"{name}_{i + 1:03d}.{fmt}"
        img.convert("RGB").save(p, "JPEG" if fmt == "jpg" else "PNG", **({"quality": 90} if fmt == "jpg" else {}))
        files.append(p)
    note = f"Показаны первые {MAX_PDF_PAGES_RENDER} страниц из {total}" if total > MAX_PDF_PAGES_RENDER else None
    if len(files) == 1:
        dst = workdir / "out" / f"{name}.{fmt}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        files[0].rename(dst)
        return Result([dst], note=note)
    dst = workdir / "out" / f"{name}_{fmt}.zip"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED) as zf:
        for f in files:
            zf.write(f, f.name)
    return Result([dst], note=(note or f"Страниц: {len(files)} — упакованы в ZIP"))


def compress(src: Path, workdir: Path) -> Result:
    _reader(src)  # проверка, что файл читается
    candidates = []
    if has("gs"):
        dst = out_path(workdir, src, "pdf", "_min")
        try:
            run(["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5", "-dPDFSETTINGS=/ebook",
                 "-dNOPAUSE", "-dBATCH", "-dQUIET", "-dDetectDuplicateImages=true",
                 f"-sOutputFile={dst}", src], timeout=600)
            candidates.append(dst)
        except RuntimeError:
            pass
    alt = tmp_dir(workdir) / f"{src.stem}_min.pdf"
    writer = PdfWriter(clone_from=str(src))
    for page in writer.pages:
        page.compress_content_streams()
    writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    with open(alt, "wb") as f:
        writer.write(f)
    candidates.append(alt)

    best = min(candidates, key=lambda p: p.stat().st_size)
    if best.stat().st_size >= src.stat().st_size * 0.97:
        return Result([src], note="PDF уже хорошо сжат — заметно уменьшить не получилось")
    final = out_path(workdir, src, "pdf", "_min")
    if best != final:
        best.replace(final)
    return Result([final])


def extract_text(src: Path, workdir: Path) -> str:
    reader = _reader(src)
    pages = [(p.extract_text() or "").strip() for p in reader.pages]
    text = "\n\n".join(pages).strip()
    # Мало текста на страницу — скорее всего скан: распознаём
    if len(text) < 30 * len(pages) and has("tesseract"):
        from app.processing.images import ocr

        ocr_pages = [ocr(img).strip() for _, _, img in _render(src, scale=2.5, limit=MAX_OCR_PAGES)]
        ocr_text = "\n\n".join(ocr_pages).strip()
        if len(ocr_text) > len(text):
            if len(pages) > MAX_OCR_PAGES:
                ocr_text += f"\n\n[Распознаны первые {MAX_OCR_PAGES} страниц из {len(pages)}]"
            return ocr_text
    return text
