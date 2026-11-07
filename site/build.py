"""Генерирует site/data.js из реестра форматов бота (app/formats.py),
чтобы сайт всегда показывал то же, что умеет бот. Запуск: python site/build.py"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# В Docker-образе Calibre установлен — показываем полный набор форматов эл. книг
_which = shutil.which
shutil.which = lambda name, *a, **k: "/usr/bin/ebook-convert" if name == "ebook-convert" else _which(name, *a, **k)

from app import formats  # noqa: E402

data = {
    "kinds": {k: sorted(v) for k, v in formats.KINDS.items()},
    "kindLabels": formats.KIND_LABELS,
    "targets": formats.TARGETS,
    "actions": {k: formats.actions_for(k) for k in formats.KIND_LABELS},
    "actionLabels": formats.ACTION_LABELS,
    "mergeable": sorted(formats.MERGEABLE_KINDS),
    "totalExtensions": sum(len(v) for v in formats.KINDS.values()),
}
out = Path(__file__).with_name("data.js")
out.write_text("window.FM_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
print(f"{out}: {data['totalExtensions']} расширений")
