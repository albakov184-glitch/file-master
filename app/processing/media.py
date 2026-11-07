"""Аудио, видео и субтитры через FFmpeg."""
import json
from pathlib import Path

from app.processing.common import Result, UserError, has, out_path, run

AUDIO_CODECS = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "flac": ["-c:a", "flac"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "wma": ["-c:a", "wmav2", "-b:a", "192k"],
    "aiff": ["-c:a", "pcm_s16be"],
}
H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
VIDEO_CODECS = {
    "mp4": H264 + ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
    "mov": H264 + ["-c:a", "aac", "-b:a", "160k"],
    "mkv": H264 + ["-c:a", "aac", "-b:a", "160k"],
    "avi": ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame", "-q:a", "3"],
    "webm": ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8",
             "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"],
}
GIF_MAX_SECONDS = 30


def _ffmpeg() -> None:
    if not has("ffmpeg"):
        raise UserError("На сервере не установлен FFmpeg")


def probe(src: Path) -> dict:
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", src],
               timeout=60)
    return json.loads(proc.stdout or "{}")


def _has_stream(info: dict, kind: str) -> bool:
    return any(s.get("codec_type") == kind for s in info.get("streams", []))


def convert(src: Path, target: str, workdir: Path) -> Result:
    _ffmpeg()
    try:
        info = probe(src)
    except RuntimeError:
        raise UserError("Не удалось прочитать медиафайл — возможно, он повреждён") from None
    dst = out_path(workdir, src, target)
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]

    if target in AUDIO_CODECS:
        if not _has_stream(info, "audio"):
            raise UserError("В файле нет звуковой дорожки")
        run(base + ["-vn", "-map_metadata", "0", *AUDIO_CODECS[target], dst], timeout=1800)
        return Result([dst])

    if not _has_stream(info, "video"):
        raise UserError("В файле нет видеодорожки")
    if target == "gif":
        vf = "fps=12,scale='min(480,iw)':-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse"
        run(base + ["-t", str(GIF_MAX_SECONDS), "-an", "-filter_complex", vf, dst], timeout=1800)
        dur = float(info.get("format", {}).get("duration") or 0)
        note = f"В GIF вошли первые {GIF_MAX_SECONDS} секунд" if dur > GIF_MAX_SECONDS else None
        return Result([dst], note=note)
    if target not in VIDEO_CODECS:
        raise UserError(f"Не умею конвертировать видео в {target}")
    audio = [] if _has_stream(info, "audio") else ["-an"]
    # Чётные размеры кадра обязательны для H.264
    run(base + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", *VIDEO_CODECS[target], *audio, dst], timeout=3600)
    return Result([dst])


def compress(src: Path, workdir: Path) -> Result:
    _ffmpeg()
    try:
        info = probe(src)
    except RuntimeError:
        raise UserError("Не удалось прочитать медиафайл — возможно, он повреждён") from None
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if _has_stream(info, "video"):
        dst = out_path(workdir, src, "mp4", "_min")
        audio = ["-c:a", "aac", "-b:a", "96k"] if _has_stream(info, "audio") else ["-an"]
        run(base + ["-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                    "-pix_fmt", "yuv420p", *audio, "-movflags", "+faststart", dst], timeout=3600)
    elif _has_stream(info, "audio"):
        dst = out_path(workdir, src, "mp3", "_min")
        run(base + ["-vn", "-c:a", "libmp3lame", "-b:a", "96k", dst], timeout=1800)
    else:
        raise UserError("В файле нет ни видео, ни звука")
    if dst.stat().st_size >= src.stat().st_size:
        return Result([src], note="Файл уже хорошо сжат — уменьшить без заметной потери качества не получилось")
    return Result([dst])


def convert_subtitles(src: Path, target: str, workdir: Path) -> Result:
    _ffmpeg()
    dst = out_path(workdir, src, target)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, dst], timeout=120)
    return Result([dst])
