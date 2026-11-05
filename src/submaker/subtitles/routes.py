"""FastAPI Router for modular Subtitle operations (Translation & Voice Transcription).
Ready to be upstreamed as a clean isolated PR to uragenky/framextv-downloader!
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..downloader.config import DOWNLOADS_DIR
from ..config import load_config
from ..sub_utils import load_subtitle, save_subtitle
from ..translator import translate_subtitles
from .transcriber import transcribe_audio_pipeline

log = logging.getLogger("submaker.subtitles.router")
router = APIRouter(prefix="/api/subtitles", tags=["subtitles"])

# In-memory subtitle job tracking for live visual progress
active_sub_jobs: Dict[str, Dict[str, Any]] = {}


class TranslateSubRequest(BaseModel):
    filename: str
    source_lang: str = "auto"
    provider: Optional[str] = None


class TranscribeAudioRequest(BaseModel):
    filename: str
    chunk_minutes: float = 4.0


@router.get("/jobs/{job_id}")
async def get_subtitle_job_status(job_id: str):
    job = active_sub_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Pekerjaan subtitle tidak ditemukan")
    return job


@router.post("/translate")
async def start_subtitle_translation(req: TranslateSubRequest, background_tasks: BackgroundTasks):
    sub_file = DOWNLOADS_DIR / req.filename
    if not sub_file.exists():
        raise HTTPException(status_code=404, detail="File subtitle tidak ditemukan di folder downloads.")

    job_id = uuid.uuid4().hex[:8]
    out_filename = f"{sub_file.stem}.id.srt"
    out_path = DOWNLOADS_DIR / out_filename

    active_sub_jobs[job_id] = {
        "job_id": job_id,
        "type": "translate",
        "target_file": out_filename,
        "status": "processing",
        "percent": 0,
        "message": "Menyiapkan antrean terjemahan..."
    }

    def _run_bg():
        try:
            cfg = load_config()
            chosen_provider = req.provider or cfg.get("provider", "llm")
            subs = load_subtitle(sub_file)

            def _on_prog(current, total):
                pct = int((current / total) * 100) if total else 0
                active_sub_jobs[job_id]["percent"] = pct
                active_sub_jobs[job_id]["message"] = f"Menerjemahkan baris {current}/{total}..."

            translated = translate_subtitles(
                subs=subs,
                provider=chosen_provider,
                api_key=cfg.get("openai_api_key"),
                base_url=cfg.get("openai_base_url"),
                model=cfg.get("openai_model"),
                source_lang=req.source_lang,
                on_progress=_on_prog
            )
            save_subtitle(translated, out_path)
            active_sub_jobs[job_id]["status"] = "completed"
            active_sub_jobs[job_id]["percent"] = 100
            active_sub_jobs[job_id]["message"] = "✔ Terjemahan selesai!"
        except Exception as e:
            log.error(f"Error in translation job {job_id}: {e}", exc_info=True)
            active_sub_jobs[job_id]["status"] = "failed"
            active_sub_jobs[job_id]["message"] = f"Gagal: {str(e)}"

    background_tasks.add_task(_run_bg)
    return {
        "success": True,
        "job_id": job_id,
        "target_file": out_filename,
        "message": f"Terjemahan subtitle dimulai untuk {req.filename}"
    }


@router.post("/transcribe-audio")
async def start_audio_transcription(req: TranscribeAudioRequest, background_tasks: BackgroundTasks):
    video_file = DOWNLOADS_DIR / req.filename
    if not video_file.exists():
        raise HTTPException(status_code=404, detail="File video tidak ditemukan di folder downloads.")

    job_id = uuid.uuid4().hex[:8]
    out_filename = f"{video_file.stem}.id.srt"
    out_path = DOWNLOADS_DIR / out_filename

    active_sub_jobs[job_id] = {
        "job_id": job_id,
        "type": "transcribe",
        "target_file": out_filename,
        "status": "processing",
        "percent": 0,
        "message": "Menyiapkan ekstraksi audio & deteksi hening..."
    }

    def _run_bg():
        try:
            cfg = load_config()

            def _on_prog(pct, total, msg):
                active_sub_jobs[job_id]["percent"] = pct
                active_sub_jobs[job_id]["message"] = msg

            transcribe_audio_pipeline(
                video_path=video_file,
                output_srt_path=out_path,
                config=cfg,
                chunk_minutes=req.chunk_minutes,
                on_progress=_on_prog
            )
            active_sub_jobs[job_id]["status"] = "completed"
            active_sub_jobs[job_id]["percent"] = 100
            active_sub_jobs[job_id]["message"] = "✔ Subtitle selesai dibuat!"
        except Exception as e:
            log.error(f"Error in transcription job {job_id}: {e}", exc_info=True)
            active_sub_jobs[job_id]["status"] = "failed"
            active_sub_jobs[job_id]["message"] = f"Gagal: {str(e)}"

    background_tasks.add_task(_run_bg)
    return {
        "success": True,
        "job_id": job_id,
        "target_file": out_filename,
        "message": f"Transkripsi audio dimulai untuk {req.filename}"
    }
