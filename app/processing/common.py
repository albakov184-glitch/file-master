import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


class UserError(Exception):
    """Ошибка, текст которой можно показать пользователю."""


@dataclass
class Result:
    files: list[Path] = field(default_factory=list)
    text: str | None = None  # превью текста для сообщения
    note: str | None = None  # пояснение к результату


def run(cmd: list, timeout: int = 600, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    log.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, text=True, errors="replace")
    except subprocess.TimeoutExpired:
        raise UserError("Обработка заняла слишком много времени") from None
    except FileNotFoundError:
        raise UserError(f"На сервере не установлен инструмент {cmd[0]}") from None
    if proc.returncode != 0:
        log.warning("command failed (%s): %s", proc.returncode, proc.stderr[-2000:])
        raise RuntimeError(f"{Path(cmd[0]).name} exited with {proc.returncode}: {proc.stderr[-500:]}")
    return proc


def has(tool: str) -> bool:
    return shutil.which(tool) is not None


def out_path(workdir: Path, src: Path, ext: str, suffix: str = "") -> Path:
    path = workdir / "out" / f"{src.stem}{suffix}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def tmp_dir(workdir: Path) -> Path:
    d = workdir / "tmp" / uuid.uuid4().hex[:8]
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
