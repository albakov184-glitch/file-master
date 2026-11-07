import shutil
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence
from pillow_heif import register_heif_opener

from app.config import OCR_LANGS
from app.processing.common import Result, UserError, has, out_path, run, tmp_dir

# ImageMagick 7 — `magick`, ImageMagick 6 — `convert`
MAGICK = shutil.which("magick") or shutil.which("convert")

register_heif_opener()  # HEIC/HEIF (фото с iPhone)

PIL_FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP", "tiff": "TIFF",
               "ico": "ICO", "avif": "AVIF", "heic": "HEIF", "pdf": "PDF"}
NO_ALPHA = {"jpg", "bmp", "pdf"}
# Форматы, которые Pillow не открывает — сначала прогоняем через ImageMagick
MAGICK_ONLY = {"svg", "psd", "xcf", "eps", "dds", "pcx", "icns"}


def open_image(src: Path, workdir: Path) -> Image.Image:
    ext = src.suffix.lower().lstrip(".")
    if ext == "svg" and has("rsvg-convert"):
        png = tmp_dir(workdir) / "svg.png"
        run(["rsvg-convert", "--width", "2048", "--keep-aspect-ratio", "-o", png, src], timeout=120)
        src = png
    elif ext in MAGICK_ONLY:
        png = tmp_dir(workdir) / "magick.png"
        density = ["-density", "200"] if ext in ("svg", "eps") else []
        run([MAGICK, *density, f"{src}[0]", "-background", "none", str(png)])
        src = png
    try:
        img = Image.open(src)
        img.load()
    except Exception:
        if not MAGICK:
            raise UserError("Не удалось открыть изображение") from None
        png = tmp_dir(workdir) / "magick.png"
        run([MAGICK, f"{src}[0]", str(png)])
        img = Image.open(png)
    return img


def _flatten(img: Image.Image, keep_alpha: bool) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P") and not keep_alpha:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    if img.mode not in ("RGB", "RGBA", "L"):
        return img.convert("RGBA" if keep_alpha else "RGB")
    return img


def to_rgb(img: Image.Image) -> Image.Image:
    return _flatten(ImageOps.exif_transpose(img), keep_alpha=False)


def convert(src: Path, target: str, workdir: Path) -> Result:
    if target not in PIL_FORMATS:
        raise UserError(f"Не умею конвертировать изображение в {target}")
    img = open_image(src, workdir)
    dst = out_path(workdir, src, target)
    frames = [f.copy() for f in ImageSequence.Iterator(img)]
    animated = len(frames) > 1

    if target in ("gif", "webp") and animated:
        frames = [_flatten(f, keep_alpha=True) for f in frames]
        frames[0].save(dst, PIL_FORMATS[target], save_all=True, append_images=frames[1:],
                       loop=img.info.get("loop", 0), duration=img.info.get("duration", 100))
    elif target in ("pdf", "tiff") and animated:  # многостраничные TIFF/GIF → многостраничный PDF/TIFF
        pages = [to_rgb(f) for f in frames]
        pages[0].save(dst, PIL_FORMATS[target], save_all=True, append_images=pages[1:])
    else:
        frame = ImageOps.exif_transpose(frames[0])
        frame = _flatten(frame, keep_alpha=target not in NO_ALPHA)
        kwargs: dict = {}
        if target == "jpg":
            kwargs = {"quality": 92, "optimize": True}
        elif target == "ico":
            frame.thumbnail((256, 256))
            kwargs = {"sizes": [s for s in [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
                                if s[0] <= max(frame.size)] or [frame.size]}
        elif target == "pdf":
            kwargs = {"resolution": 150}
        frame.save(dst, PIL_FORMATS[target], **kwargs)
    return Result([dst])


def compress(src: Path, workdir: Path) -> Result:
    img = open_image(src, workdir)
    ext = src.suffix.lower().lstrip(".")
    img = ImageOps.exif_transpose(img)
    img.thumbnail((2560, 2560))
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)

    candidates: list[Path] = []
    if ext in ("png", "gif", "bmp", "tiff", "tif") and has_alpha:
        p = out_path(workdir, src, "png", "_min")
        img.convert("RGBA").quantize(256, method=Image.Quantize.FASTOCTREE).save(p, "PNG", optimize=True)
        candidates.append(p)
        w = out_path(workdir, src, "webp", "_min")
        img.save(w, "WEBP", quality=75, method=6)
        candidates.append(w)
    else:
        target = "webp" if ext == "webp" else "jpg"
        p = out_path(workdir, src, target, "_min")
        rgb = _flatten(img, keep_alpha=False)
        if target == "jpg":
            rgb.save(p, "JPEG", quality=72, optimize=True, progressive=True)
        else:
            rgb.save(p, "WEBP", quality=72, method=6)
        candidates.append(p)

    best = min(candidates, key=lambda p: p.stat().st_size)
    if best.stat().st_size >= src.stat().st_size:
        return Result([src], note="Файл уже хорошо сжат — уменьшить без потери качества не получилось")
    return Result([best])


def ocr(img: Image.Image) -> str:
    import pytesseract

    if not has("tesseract"):
        raise UserError("На сервере не установлен Tesseract для распознавания текста")
    gray = to_rgb(img).convert("L")
    if max(gray.size) < 1500:  # мелкие картинки распознаются лучше после увеличения
        k = 1500 / max(gray.size)
        gray = gray.resize((int(gray.width * k), int(gray.height * k)))
    return pytesseract.image_to_string(gray, lang=OCR_LANGS)


def extract_text(src: Path, workdir: Path) -> str:
    return ocr(open_image(src, workdir))
