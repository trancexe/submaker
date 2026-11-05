"""Audio transcription engine supporting faster-whisper (local CPU/GPU) and optional cloud ASR."""

import os
from pathlib import Path
from typing import Optional, Callable

# Fix for PyAV v19+ where 'metadata_errors' was removed in av.open
try:
    import av
    _orig_av_open = av.open
    def _patched_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _patched_av_open
except Exception:
    pass

import pysubs2
from pysubs2 import SSAFile, SSAEvent


def transcribe_local_whisper(
    audio_path: str | Path,
    model_size: str = "medium",
    language: str = "ja",
    device: str = "cpu",
    compute_type: str = "int8",
    on_progress: Optional[Callable[[float, str], None]] = None
) -> SSAFile:
    """
    Transcribe audio file using faster-whisper with Silero VAD filter.
    Returns an SSAFile ready for editing or translation.
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    # Use VAD filter to avoid transcribing non-speech (BGM, sound effects)
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        beam_size=5,
        word_timestamps=False
    )

    subs = SSAFile()
    subs.info["Title"] = f"Transcribed by submaker ({model_size})"
    subs.info["ScriptType"] = "v4.00+"

    total_duration = info.duration or 1.0

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        
        # pysubs2 works in milliseconds
        start_ms = int(seg.start * 1000)
        end_ms = int(seg.end * 1000)
        
        event = SSAEvent(start=start_ms, end=end_ms, text=text)
        subs.events.append(event)
        
        if on_progress:
            progress = min(1.0, seg.end / total_duration)
            on_progress(progress, text)

    return subs


def transcribe_groq_whisper(audio_path: str | Path, api_key: str | None = None) -> SSAFile:
    """
    Super-fast cloud Whisper transcription using Groq API (whisper-large-v3).
    Useful when processing on CPU is too slow for 2-hour movies.
    """
    import httpx
    api_key = api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is required for Groq Whisper transcription.")

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    with open(audio_path, "rb") as f:
        files = {"file": (Path(audio_path).name, f, "audio/wav")}
        data = {
            "model": "whisper-large-v3",
            "language": "ja",
            "response_format": "verbose_json"
        }
        resp = httpx.post(url, headers=headers, files=files, data=data, timeout=300.0)
        resp.raise_for_status()
        res_json = resp.json()

    subs = SSAFile()
    for seg in res_json.get("segments", []):
        start_ms = int(seg["start"] * 1000)
        end_ms = int(seg["end"] * 1000)
        text = seg["text"].strip()
        if text:
            subs.events.append(SSAEvent(start=start_ms, end=end_ms, text=text))

    return subs
