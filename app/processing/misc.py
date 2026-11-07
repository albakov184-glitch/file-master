"""Шрифты (TTF/OTF/WOFF/WOFF2)."""
from pathlib import Path

from app.processing.common import Result, UserError, out_path


def convert_font(src: Path, target: str, workdir: Path) -> Result:
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(str(src))
    except Exception:
        raise UserError("Не удалось прочитать шрифт") from None
    is_cff = "CFF " in font or "CFF2" in font
    if target == "ttf" and is_cff:
        raise UserError("Это шрифт с CFF-контурами — его можно сохранить как OTF, WOFF или WOFF2, но не TTF")
    if target == "otf" and not is_cff:
        raise UserError("Это шрифт с TrueType-контурами — его можно сохранить как TTF, WOFF или WOFF2, но не OTF")
    font.flavor = target if target in ("woff", "woff2") else None
    dst = out_path(workdir, src, target)
    font.save(str(dst))
    return Result([dst])
