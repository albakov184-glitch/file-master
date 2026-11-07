"""Архивы: распаковка любых (7-Zip), упаковка в ZIP / 7Z / TAR.GZ."""
import shutil
import tarfile
import zipfile
from pathlib import Path

from app.config import MAX_ARCHIVE_FILES_SENT, MAX_ARCHIVE_UNPACKED
from app.processing.common import Result, UserError, out_path, run, tmp_dir

# 7zz — официальный 7-Zip (умеет RAR5), 7z — p7zip или новый 7-Zip в Ubuntu
SEVEN_ZIP = shutil.which("7zz") or shutil.which("7z")


def _safe_members(root: Path) -> list[Path]:
    files = []
    root = root.resolve()
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            p.unlink()
            continue
        if p.is_file() and p.resolve().is_relative_to(root):
            files.append(p)
    return files


def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    # Windows-архиваторы пишут русские имена в cp866 без флага UTF-8
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def unpack(src: Path, workdir: Path) -> Path:
    dest = tmp_dir(workdir)
    name = src.name.lower()
    if name.endswith(".zip") and zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            if any(i.flag_bits & 0x1 for i in zf.infolist()):
                raise UserError("Архив защищён паролем")
            if sum(i.file_size for i in zf.infolist()) > MAX_ARCHIVE_UNPACKED:
                raise UserError("Архив слишком большой в распакованном виде")
            for info in zf.infolist():
                target = (dest / _fix_zip_name(info)).resolve()
                if not target.is_relative_to(dest.resolve()):
                    continue  # защита от «../» в именах
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as s, open(target, "wb") as d:
                    d.write(s.read())
        return dest
    if not SEVEN_ZIP:
        raise UserError("На сервере не установлен 7-Zip")
    try:
        listing = run([SEVEN_ZIP, "l", "-slt", "-p", src], timeout=120).stdout
    except RuntimeError as e:
        if "password" in str(e).lower() or "Wrong password" in str(e):
            raise UserError("Архив защищён паролем") from None
        raise UserError("Не удалось открыть архив — возможно, он повреждён") from None
    total = sum(int(line.split("=", 1)[1].strip() or 0) for line in listing.splitlines()
                if line.startswith("Size = "))
    if total > MAX_ARCHIVE_UNPACKED:
        raise UserError("Архив слишком большой в распакованном виде")
    try:
        run([SEVEN_ZIP, "x", "-y", "-p", f"-o{dest}", src], timeout=1800)
    except RuntimeError:
        raise UserError("Не удалось распаковать архив (повреждён или защищён паролем)") from None
    # .tar.gz → после 7z получается .tar, распаковываем второй слой
    inner = _safe_members(dest)
    if len(inner) == 1 and inner[0].suffix == ".tar":
        tar = inner[0]
        dest2 = tmp_dir(workdir)
        run([SEVEN_ZIP, "x", "-y", f"-o{dest2}", tar], timeout=1800)
        return dest2
    return dest


def extract(src: Path, workdir: Path) -> Result:
    root = unpack(src, workdir)
    files = _safe_members(root)
    if not files:
        raise UserError("Архив пустой")
    note = f"Файлов в архиве: {len(files)}"
    if len(files) > MAX_ARCHIVE_FILES_SENT:
        note += f". Отправляю первые {MAX_ARCHIVE_FILES_SENT}"
    out = []
    for f in files[:MAX_ARCHIVE_FILES_SENT]:
        rel = f.relative_to(root)
        dst = workdir / "out" / "_".join(rel.parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        f.rename(dst)
        out.append(dst)
    return Result(out, note=note)


def pack(paths: list[Path], target: str, workdir: Path, name: str, base: Path | None = None) -> Path:
    dst = workdir / "out" / f"{name}.{target}"
    dst.parent.mkdir(parents=True, exist_ok=True)

    def arcname(p: Path) -> str:
        return str(p.relative_to(base)) if base else p.name

    if target == "zip":
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for p in paths:
                zf.write(p, arcname(p))
    elif target == "tar.gz":
        with tarfile.open(dst, "w:gz", compresslevel=9) as tf:
            for p in paths:
                tf.add(p, arcname(p))
    elif target == "7z":
        import py7zr

        with py7zr.SevenZipFile(dst, "w") as zf:
            for p in paths:
                zf.write(p, arcname(p))
    else:
        raise UserError(f"Не умею упаковывать в {target}")
    return dst


def convert(src: Path, target: str, workdir: Path) -> Result:
    root = unpack(src, workdir)
    files = _safe_members(root)
    if not files:
        raise UserError("Архив пустой")
    stem = src.name.split(".")[0] or "archive"
    return Result([pack(files, target, workdir, stem, base=root)])


def zip_file(src: Path, workdir: Path) -> Result:
    dst = pack([src], "zip", workdir, src.stem)
    note = None
    if dst.stat().st_size > src.stat().st_size * 0.95:
        note = "Этот формат уже сжат внутри — ZIP почти не уменьшил размер"
    return Result([dst], note=note)
