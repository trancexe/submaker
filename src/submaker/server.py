"""Web server and API endpoints for submaker Web GUI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .downloader.config import DOWNLOADS_DIR
from .downloader.parser import parse_link, ParsedLink
from .downloader.framex_client import (
    fetch_media_info,
    MediaInfo,
    MediaDetails,
    StreamSource,
    Subtitle,
)
from .downloader.engine import (
    DownloadProgress,
    TaskStatus,
    get_progress,
    cancel_task,
    list_tasks,
    run_download_task,
)
from .config import load_config, save_config
from .sub_utils import load_subtitle, save_subtitle
from .transcriber import transcribe_local_whisper, transcribe_groq_whisper
from .translator import translate_subtitles
from .subtitles.routes import router as subtitles_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("submaker.server")

# Patch PyAV v19+ metadata_errors issue globally
try:
    import av
    _orig_av_open = av.open
    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _safe_av_open
except Exception:
    pass

app = FastAPI(title="Submaker Studio Web GUI", version="1.0.0")

# Mount modular subtitle operations router
app.include_router(subtitles_router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory registry for subtitle generation tasks
sub_tasks: Dict[str, Dict[str, Any]] = {}


class InspectRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    source_url: str
    output_filename: str
    stream_type: str = "hls"
    headers: dict[str, str] = {}
    skip_proxy: bool = False
    subtitle_urls: list[str] = []
    auto_translate_id: bool = True  # Automatically generate Indonesian subs!


class TranslateSubRequest(BaseModel):
    sub_filename: str
    source_lang: str = "auto"
    provider: Optional[str] = None


class MakeRawSubRequest(BaseModel):
    video_filename: str
    model_size: str = "medium"
    provider: Optional[str] = None
    use_groq: bool = False


class ConfigUpdateRequest(BaseModel):
    provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    groq_api_key: Optional[str] = None
    whisper_model: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Index HTML not found")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.post("/api/inspect")
async def inspect_media(req: InspectRequest):
    try:
        parsed = parse_link(req.url)
        info: MediaInfo = await fetch_media_info(parsed)
        return info
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Error inspecting media: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gagal memeriksa media: {e}")


@app.post("/api/download")
async def start_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    out_name = re.sub(r'[\\/*?:"<>|]', "", req.output_filename).strip(". ")
    if out_name.endswith(".mp4"):
        out_name = out_name[:-4]  # Engine adds .mp4 extension automatically

    source = StreamSource(
        url=req.source_url,
        quality="auto",
        stream_type=req.stream_type,
        server="WebUI",
        headers=req.headers,
        skip_proxy=req.skip_proxy,
    )

    subtitles = [
        Subtitle(url=u, label=f"sub_{i}", language="sub", fmt="vtt")
        for i, u in enumerate(req.subtitle_urls)
    ]

    # Run download using engine's native run_download_task signature: (source, subtitles, filename_base)
    task_id = await run_download_task(
        source=source,
        subtitles=subtitles,
        filename_base=out_name,
    )

    if req.auto_translate_id:
        background_tasks.add_task(_watch_and_translate_when_done, task_id, out_name)

    return {"success": True, "task_id": task_id, "filename": out_name}


async def _watch_and_translate_when_done(task_id: str, out_name: str):
    """Wait for download task to complete, then auto-generate Indonesian subtitles."""
    while True:
        prog = get_progress(task_id)
        if not prog:
            break
        if prog.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            break
        await asyncio.sleep(1.0)

    prog = get_progress(task_id)
    if prog and prog.status == TaskStatus.COMPLETED:
        log.info(f"Task {task_id} completed. Checking for automatic Indonesian translation...")
        base_stem = Path(out_name).stem
        downloaded_subs = list(DOWNLOADS_DIR.glob(f"{base_stem}*.srt")) + list(DOWNLOADS_DIR.glob(f"{base_stem}*.vtt"))
        
        non_id_subs = [s for s in downloaded_subs if not s.name.endswith(".id.srt") and not s.name.endswith(".id.vtt")]
        
        cfg = load_config()
        if non_id_subs:
            sub_to_trans = non_id_subs[0]
            log.info(f"Auto-translating downloaded subtitle: {sub_to_trans.name}")
            try:
                subs = load_subtitle(sub_to_trans)
                out_sub_path = DOWNLOADS_DIR / f"{base_stem}.id.srt"
                translated = translate_subtitles(
                    subs=subs,
                    provider=cfg.get("provider", "google"),
                    api_key=cfg.get("openai_api_key"),
                    base_url=cfg.get("openai_base_url"),
                    model=cfg.get("openai_model"),
                    source_lang="auto"
                )
                save_subtitle(translated, out_sub_path)
                log.info(f"Successfully generated Indonesian subtitle: {out_sub_path.name}")
            except Exception as e:
                log.error(f"Failed auto-translating subtitle: {e}")
        else:
            video_file = DOWNLOADS_DIR / out_name
            if video_file.exists():
                log.info(f"No subtitle found. Triggering Whisper ASR for video: {video_file.name}")
                try:
                    from .extractor import extract_audio
                    temp_wav = DOWNLOADS_DIR / f"{base_stem}_temp.wav"
                    extract_audio(video_file, temp_wav)
                    
                    subs_ja = transcribe_local_whisper(
                        temp_wav,
                        model_size=cfg.get("whisper_model", "medium"),
                        language="ja"
                    )
                    out_sub_path = DOWNLOADS_DIR / f"{base_stem}.id.srt"
                    translated = translate_subtitles(
                        subs=subs_ja,
                        provider=cfg.get("provider", "google"),
                        api_key=cfg.get("openai_api_key"),
                        base_url=cfg.get("openai_base_url"),
                        model=cfg.get("openai_model"),
                        source_lang="ja"
                    )
                    save_subtitle(translated, out_sub_path)
                    log.info(f"Whisper + translation completed: {out_sub_path.name}")
                    if temp_wav.exists():
                        temp_wav.unlink()
                except Exception as e:
                    log.error(f"Whisper auto-generation failed: {e}")


@app.get("/api/progress/{task_id}")
async def stream_progress(task_id: str):
    async def event_generator():
        while True:
            prog = get_progress(task_id)
            if not prog:
                yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                return

            # Helper for formatting speed and ETA safely
            speed_str = "-- KB/s"
            if prog.speed_bps > 0:
                if prog.speed_bps >= 1_048_576:
                    speed_str = f"{prog.speed_bps / 1_048_576:.1f} MB/s"
                else:
                    speed_str = f"{prog.speed_bps / 1024:.0f} KB/s"

            eta_str = "--"
            if prog.eta_seconds > 0:
                m = int(prog.eta_seconds // 60)
                s = int(prog.eta_seconds % 60)
                eta_str = f"{m}m {s}s" if m > 0 else f"{s}s"

            data = {
                "task_id": prog.task_id,
                "status": prog.status.value,
                "total_segments": prog.total_segments,
                "downloaded_segments": prog.downloaded_segments,
                "bytes_downloaded": prog.bytes_downloaded,
                "percent": round(prog.percent, 1),
                "speed": speed_str,
                "eta": eta_str,
                "error": prog.error,
                "filename": prog.filename,
            }
            yield f"data: {json.dumps(data)}\n\n"

            if prog.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/files")
async def list_files():
    """List downloaded video and subtitle files."""
    files = []
    for p in sorted(DOWNLOADS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and not p.name.startswith("."):
            size_mb = p.stat().st_size / (1024 * 1024)
            is_sub = p.suffix in [".srt", ".vtt", ".ass"]
            is_video = p.suffix in [".mp4", ".mkv", ".ts"]
            files.append({
                "name": p.name,
                "size_mb": round(size_mb, 2),
                "is_sub": is_sub,
                "is_video": is_video,
                "is_id_sub": ".id." in p.name
            })
    return files


@app.get("/api/files/{filename}")
async def download_file(filename: str):
    file_path = DOWNLOADS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    return FileResponse(path=str(file_path), filename=filename)


@app.delete("/api/files/{filename}")
async def delete_file(filename: str):
    file_path = DOWNLOADS_DIR / filename
    if file_path.exists() and file_path.is_file():
        file_path.unlink()
        return {"success": True, "message": f"{filename} dihapus"}
    raise HTTPException(status_code=404, detail="File tidak ditemukan")


# Direct Subtitle Translation on any file in downloads
@app.post("/api/translate-subtitle")
async def api_translate_subtitle(req: TranslateSubRequest, background_tasks: BackgroundTasks):
    sub_path = DOWNLOADS_DIR / req.sub_filename
    if not sub_path.exists():
        raise HTTPException(status_code=404, detail="File subtitle tidak ditemukan")

    cfg = load_config()
    chosen_provider = req.provider or cfg.get("provider", "google")
    out_filename = f"{sub_path.stem}.id.srt"
    out_path = DOWNLOADS_DIR / out_filename

    def _task():
        subs = load_subtitle(sub_path)
        translated = translate_subtitles(
            subs=subs,
            provider=chosen_provider,
            api_key=cfg.get("openai_api_key"),
            base_url=cfg.get("openai_base_url"),
            model=cfg.get("openai_model"),
            source_lang=req.source_lang
        )
        save_subtitle(translated, out_path)

    background_tasks.add_task(_task)
    return {"success": True, "message": f"Terjemahan dimulai. File output: {out_filename}"}


# Whisper RAW generation for any video file in downloads
@app.post("/api/make-raw-subtitle")
async def api_make_raw_subtitle(req: MakeRawSubRequest, background_tasks: BackgroundTasks):
    video_path = DOWNLOADS_DIR / req.video_filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="File video tidak ditemukan")

    cfg = load_config()
    chosen_provider = req.provider or cfg.get("provider", "google")
    out_filename = f"{video_path.stem}.id.srt"
    out_path = DOWNLOADS_DIR / out_filename

    def _task():
        from .extractor import extract_audio
        temp_wav = DOWNLOADS_DIR / f"{video_path.stem}_temp.wav"
        try:
            extract_audio(video_path, temp_wav)
            if req.use_groq:
                subs_ja = transcribe_groq_whisper(temp_wav, api_key=cfg.get("groq_api_key"))
            else:
                subs_ja = transcribe_local_whisper(
                    temp_wav,
                    model_size=req.model_size or cfg.get("whisper_model", "medium"),
                    language="ja"
                )
            translated = translate_subtitles(
                subs=subs_ja,
                provider=chosen_provider,
                api_key=cfg.get("openai_api_key"),
                base_url=cfg.get("openai_base_url"),
                model=cfg.get("openai_model"),
                source_lang="ja"
            )
            save_subtitle(translated, out_path)
        finally:
            if temp_wav.exists():
                temp_wav.unlink()

    background_tasks.add_task(_task)
    return {"success": True, "message": f"Whisper ASR & Terjemahan dimulai. Target: {out_filename}"}


@app.get("/api/config")
async def get_config_endpoint():
    cfg = load_config()
    # Mask keys
    masked_cfg = dict(cfg)
    for k in ["openai_api_key", "groq_api_key"]:
        v = masked_cfg.get(k)
        if v and len(v) > 8:
            masked_cfg[k] = v[:4] + "..." + v[-4:]
    return masked_cfg


@app.post("/api/config")
async def update_config_endpoint(req: ConfigUpdateRequest):
    cfg = load_config()
    if req.provider:
        cfg["provider"] = req.provider
    if req.openai_api_key:
        cfg["openai_api_key"] = req.openai_api_key
    if req.openai_base_url:
        cfg["openai_base_url"] = req.openai_base_url
    if req.openai_model:
        cfg["openai_model"] = req.openai_model
    if req.groq_api_key:
        cfg["groq_api_key"] = req.groq_api_key
    if req.whisper_model:
        cfg["whisper_model"] = req.whisper_model

    save_config(cfg)
    return {"success": True, "config": cfg}
