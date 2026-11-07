import zipfile

import pytest
from PIL import Image

from app.formats import ext_of, kind_of, targets_for
from app.processing import process
from app.processing.common import UserError

CONVERSIONS = [
    # (образец, целевой формат)
    *[("png", t) for t in ("jpg", "webp", "pdf", "gif", "bmp", "tiff", "ico", "avif", "heic")],
    ("heic", "jpg"), ("svg", "png"), ("jpg", "png"), ("gif", "webp"),
    *[("docx", t) for t in ("pdf", "doc", "odt", "rtf", "txt", "html", "epub", "fb2", "md")],
    ("odt", "docx"), ("rtf", "pdf"), ("txt", "docx"), ("txt", "pdf"),
    *[("xlsx", t) for t in ("pdf", "xls", "ods", "csv", "html")], ("csv", "xlsx"),
    *[("pptx", t) for t in ("pdf", "odp", "ppt", "png")],
    *[("md", t) for t in ("pdf", "docx", "html", "epub", "fb2", "txt", "odt", "rtf")],
    ("html", "pdf"), ("html", "docx"), ("epub", "fb2"), ("fb2", "epub"), ("epub", "docx"),
    *[("pdf", t) for t in ("docx", "jpg", "png", "txt", "html", "epub")],
    *[("wav", t) for t in ("mp3", "ogg", "opus", "flac", "m4a", "aac", "wma", "aiff")], ("mp3", "wav"),
    *[("mp4", t) for t in ("mkv", "avi", "mov", "webm", "gif", "mp3", "m4a", "wav")], ("mov", "mp4"),
    ("zip", "7z"), ("zip", "tar.gz"), ("tar.gz", "zip"), ("7z", "zip"),
    ("ttf", "woff"), ("ttf", "woff2"),
    ("srt", "vtt"), ("srt", "ass"),
    ("json", "pdf"), ("json", "docx"),
]


def _check_output(path, target):
    assert path.exists() and path.stat().st_size > 0, path
    assert path.name.lower().endswith("." + target), path.name
    if target in ("png", "jpg", "webp", "gif", "bmp", "tiff", "avif"):
        Image.open(path).verify()
    if target in ("zip",):
        assert zipfile.is_zipfile(path)
    if target == "pdf":
        assert path.read_bytes()[:4] == b"%PDF"


@pytest.mark.parametrize(("sample", "target"), CONVERSIONS, ids=[f"{s}->{t}" for s, t in CONVERSIONS])
def test_convert(samples, workdir, sample, target):
    src = samples[sample]
    kind = kind_of(ext_of(src.name))
    assert target in targets_for(kind, ext_of(src.name)), f"{target} не предлагается для {sample}"
    res = process("convert", {"target": target}, [(src, kind)], workdir)
    assert len(res.files) == 1
    out = res.files[0]
    if sample in ("pptx", "pdf") and target in ("png", "jpg") and out.suffix == ".zip":
        return  # многостраничный документ → архив картинок
    _check_output(out, target)


@pytest.mark.parametrize("sample", ["png", "jpg", "scan_pdf", "docx", "xlsx", "pptx", "md", "html", "epub",
                                    "fb2", "txt", "json", "odt", "rtf", "srt", "pdf"])
def test_extract_text(samples, workdir, sample):
    src = samples[sample]
    res = process("text", {}, [(src, kind_of(ext_of(src.name)))], workdir)
    text = res.text.lower()
    assert ("привет" in text or "hello" in text or "анна" in text), res.text[:200]


@pytest.mark.parametrize("sample", ["jpg", "png", "pdf", "mp4", "wav", "bin", "docx"])
def test_compress(samples, workdir, sample):
    src = samples[sample]
    kind = kind_of(ext_of(src.name))
    op = "compress" if kind in ("image", "pdf", "audio", "video", "other") else "zip"
    res = process(op, {}, [(src, kind)], workdir)
    assert res.files and res.files[0].exists()


def test_merge_mixed(samples, workdir):
    from pypdf import PdfReader

    inputs = [(samples[s], kind_of(ext_of(samples[s].name))) for s in ("pdf", "png", "docx", "md", "xlsx")]
    res = process("merge", {}, inputs, workdir)
    assert len(PdfReader(res.files[0]).pages) >= 5


def test_split(samples, workdir):
    res = process("merge", {}, [(samples["pdf"], "pdf"), (samples["scan_pdf"], "pdf")], workdir)
    split = process("split", {}, [(res.files[0], "pdf")], workdir)
    with zipfile.ZipFile(split.files[0]) as zf:
        assert len(zf.namelist()) == 2


@pytest.mark.parametrize("sample", ["zip", "tar.gz", "7z"])
def test_extract_archive(samples, workdir, sample):
    res = process("extract", {}, [(samples[sample], "archive")], workdir)
    assert len(res.files) == 2
    if sample == "zip":
        assert {f.name for f in res.files} == {"папка_текст.txt", "картинка.png"}


def test_user_errors(samples, workdir):
    with pytest.raises(UserError):
        process("text", {}, [(samples["mp3"], "audio")], workdir)
    with pytest.raises(UserError):
        process("merge", {}, [(samples["pdf"], "pdf")], workdir)
    with pytest.raises(UserError):
        process("convert", {"target": "mp4"}, [(samples["wav"], "audio")], workdir)


def test_registry():
    assert kind_of(ext_of("Фото.HEIC")) == "image"
    assert kind_of(ext_of("a.tar.gz")) == "archive"
    assert kind_of(ext_of("x.ts")) == "video"
    assert kind_of(ext_of("file.unknownext")) == "other"
    assert "jpg" not in targets_for("image", "jpeg")
