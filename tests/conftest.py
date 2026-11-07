"""Генерирует настоящие файлы разных форматов для тестов (один раз на сессию)."""
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

TEXT = "Привет, мир! Hello world 12345"


def _font(size: int):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> dict[str, Path]:
    import pillow_heif

    pillow_heif.register_heif_opener()
    d = tmp_path_factory.mktemp("samples")
    s: dict[str, Path] = {}

    img = Image.new("RGB", (900, 300), "white")
    ImageDraw.Draw(img).text((30, 110), TEXT, fill="black", font=_font(44))
    for ext, fmt in [("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP"), ("bmp", "BMP"), ("tiff", "TIFF"),
                     ("gif", "GIF"), ("heic", "HEIF")]:
        s[ext] = d / f"image.{ext}"
        img.save(s[ext], fmt)
    s["svg"] = d / "vector.svg"
    s["svg"].write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                        '<rect width="120" height="80" fill="#3a7"/><circle cx="60" cy="40" r="25" fill="#fff"/></svg>')

    s["md"] = d / "notes.md"
    s["md"].write_text(f"# Заголовок\n\n{TEXT}\n\n- пункт 1\n- пункт 2\n", encoding="utf-8")
    s["html"] = d / "page.html"
    s["html"].write_text(f"<html><body><h1>Страница</h1><p>{TEXT}</p></body></html>", encoding="utf-8")
    s["txt"] = d / "plain.txt"
    s["txt"].write_text(TEXT, encoding="utf-8")
    s["json"] = d / "data.json"
    s["json"].write_text('{"привет": "мир", "n": 1}', encoding="utf-8")
    s["csv"] = d / "table.csv"
    s["csv"].write_text("Имя,Возраст\nАнна,30\nБорис,25\n", encoding="utf-8")
    s["srt"] = d / "subs.srt"
    s["srt"].write_text("1\n00:00:01,000 --> 00:00:02,500\nПривет\n\n2\n00:00:03,000 --> 00:00:04,000\nМир\n",
                        encoding="utf-8")

    import docx

    doc = docx.Document()
    doc.add_heading("Документ", 1)
    doc.add_paragraph(TEXT)
    s["docx"] = d / "document.docx"
    doc.save(s["docx"])

    for ext in ("epub", "fb2", "pptx", "odt", "rtf"):
        s[ext] = d / f"from_md.{ext}"
        subprocess.run(["pandoc", s["md"], "-s", "--metadata", "title=Test", "-o", s[ext]], check=True)

    lo_out = d / "lo"
    profile = d / "lo_profile"
    for src, fmt in ((s["docx"], "pdf"), (s["csv"], "xlsx")):
        subprocess.run(["soffice", "--headless", f"-env:UserInstallation=file://{profile}", "--convert-to", fmt,
                        "--outdir", lo_out, src], check=True, capture_output=True)
    s["pdf"] = lo_out / "document.pdf"
    s["xlsx"] = lo_out / "table.xlsx"
    s["scan_pdf"] = d / "scan.pdf"  # PDF без текстового слоя — проверка OCR
    img.save(s["scan_pdf"], "PDF", resolution=100)

    ff = ["ffmpeg", "-y", "-loglevel", "error"]
    s["wav"] = d / "sound.wav"
    subprocess.run(ff + ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", s["wav"]], check=True)
    s["mp3"] = d / "sound.mp3"
    subprocess.run(ff + ["-i", s["wav"], s["mp3"]], check=True)
    s["mp4"] = d / "clip.mp4"
    subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15", "-f", "lavfi", "-i",
                         "sine=duration=2", "-shortest", "-pix_fmt", "yuv420p", s["mp4"]], check=True)
    s["mov"] = d / "clip.mov"
    subprocess.run(ff + ["-i", s["mp4"], "-c", "copy", s["mov"]], check=True)

    s["zip"] = d / "архив.zip"
    with zipfile.ZipFile(s["zip"], "w") as zf:
        zf.write(s["txt"], "папка/текст.txt")
        zf.write(s["png"], "картинка.png")
    s["tar.gz"] = d / "bundle.tar.gz"
    with tarfile.open(s["tar.gz"], "w:gz") as tf:
        tf.add(s["txt"], "a.txt")
        tf.add(s["md"], "b.md")
    s["7z"] = d / "bundle.7z"
    subprocess.run(["7z", "a", "-bd", s["7z"], s["txt"], s["json"]], check=True, capture_output=True)

    ttf = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if ttf.exists():
        s["ttf"] = d / "font.ttf"
        shutil.copy(ttf, s["ttf"])

    s["bin"] = d / "blob.xyz"
    s["bin"].write_bytes(b"\0" * 5000 + b"data" * 1000)
    return s


@pytest.fixture
def workdir(tmp_path) -> Path:
    return tmp_path
