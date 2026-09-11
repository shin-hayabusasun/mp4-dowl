from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from shutil import which
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_from_directory
from yt_dlp import YoutubeDL

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None


RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DOWNLOAD_DIR = APP_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

app = Flask(__name__, static_folder=str(RESOURCE_DIR / "static"), static_url_path="")
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in ALLOWED_HOSTS


def job_update(job_id: str, **values: Any) -> None:
    with jobs_lock:
        jobs.setdefault(job_id, {}).update(values)


def public_file(file_path: str | None) -> dict[str, str] | None:
    if not file_path:
        return None
    path = Path(file_path).resolve()
    try:
        path.relative_to(DOWNLOAD_DIR.resolve())
    except ValueError:
        return None
    if not path.exists():
        return None
    return {"name": path.name, "url": f"/downloads/{path.name}"}


def ffmpeg_location() -> str | None:
    system_ffmpeg = which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    if imageio_ffmpeg:
        bundled_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_ffmpeg:
            return bundled_ffmpeg
    return None


def output_file_from_info(ydl: YoutubeDL, info: dict[str, Any], last_file: str | None) -> dict[str, str] | None:
    candidates: list[str | None] = [
        info.get("filepath"),
        info.get("_filename"),
    ]
    for requested in info.get("requested_downloads") or []:
        if isinstance(requested, dict):
            candidates.extend([requested.get("filepath"), requested.get("_filename")])
    candidates.extend([ydl.prepare_filename(info), last_file])

    for candidate in candidates:
        file_info = public_file(candidate)
        if file_info:
            return file_info
    return None


def download_video(job_id: str, url: str, audio_only: bool) -> None:
    last_file: str | None = None

    def progress_hook(data: dict[str, Any]) -> None:
        nonlocal last_file
        filename = data.get("filename") or data.get("tmpfilename")
        if filename:
            last_file = filename

        if data["status"] == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            percent = round((downloaded / total) * 100, 1) if total else None
            job_update(
                job_id,
                status="downloading",
                percent=percent,
                speed=data.get("speed"),
                eta=data.get("eta"),
            )
        elif data["status"] == "finished":
            job_update(job_id, status="processing", percent=100)

    ffmpeg = ffmpeg_location()
    ydl_opts: dict[str, Any] = {
        "outtmpl": str(DOWNLOAD_DIR / "%(title).180B [%(id)s].%(ext)s"),
        "progress_hooks": [progress_hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
    }
    if ffmpeg:
        ydl_opts["ffmpeg_location"] = ffmpeg

    if audio_only:
        ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
    else:
        if not ffmpeg:
            job_update(job_id, status="error", error="ffmpeg が見つからないため、音声付き動画を作成できません。")
            return
        ydl_opts["format"] = (
            "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/"
            "bv*[ext=webm][height<=1080]+ba[ext=webm]/"
            "bv*[height<=1080]+ba/"
            "bv*+ba/"
            "best[ext=mp4]/"
            "best"
        )

    try:
        job_update(job_id, status="starting", percent=0)
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_file = output_file_from_info(ydl, info, last_file)
            if not final_file:
                raise RuntimeError("Downloaded file could not be found.")
            job_update(
                job_id,
                status="done",
                percent=100,
                title=info.get("title"),
                file=final_file,
            )
    except Exception as exc:  # yt-dlp returns user-facing details in exception text.
        job_update(job_id, status="error", error=str(exc))


@app.get("/")
def index() -> Response:
    return app.send_static_file("index.html")


@app.post("/api/info")
def get_info() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    if not is_youtube_url(url):
        return jsonify({"error": "YouTube のURLを入力してください。"}), 400

    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url"),
        }
    )


@app.post("/api/download")
def create_download() -> tuple[Response, int] | Response:
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    audio_only = bool(payload.get("audioOnly"))
    if not is_youtube_url(url):
        return jsonify({"error": "YouTube のURLを入力してください。"}), 400

    job_id = uuid.uuid4().hex
    job_update(job_id, status="queued", percent=0)
    thread = threading.Thread(target=download_video, args=(job_id, url, audio_only), daemon=True)
    thread.start()
    return jsonify({"jobId": job_id})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str) -> Response:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "ジョブが見つかりません。"}), 404
    return jsonify(job)


@app.get("/api/files")
def list_files() -> Response:
    files = [
        {"name": path.name, "url": f"/downloads/{path.name}", "size": path.stat().st_size}
        for path in sorted(DOWNLOAD_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
        if path.is_file()
    ]
    return jsonify({"files": files})


@app.get("/downloads/<path:filename>")
def serve_download(filename: str) -> Response:
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=not getattr(sys, "frozen", False))
