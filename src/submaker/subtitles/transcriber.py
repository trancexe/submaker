"""Audio-to-Subtitle transcription client supporting Omniroute Multimodal Audio, Whisper API, and Local Faster-Whisper."""

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
import httpx
import pysubs2
from pysubs2 import SSAFile, SSAEvent

log = logging.getLogger("submaker.transcriber")

FANSUB_AUDIO_PROMPT = """Dengarkan audio dialog percakapan anime Jepang berikut ini dengan seksama.
Tugas: Buatkan subtitle SRT Bahasa Indonesia yang SANGAT PRESISI dan SINKRON dengan suara ucapan karakter (anime fansub).

Aturan Wajib:
1. Mulai timestamp (start time) TEPAT pada milidetik saat karakter mengeluarkan suara vokal (jangan mendahului suara!).
2. Akhiri timestamp saat karakter selesai berbicara.
3. Terjemahkan dialog ke Bahasa Indonesia alami, ekspresif, dan luwes.
4. Pertahankan honorifik Jepang jika cocok (-san, -kun, -chan, -senpai, -sama, sensei).
5. Abaikan musik latar/BGM jika tidak ada orang berbicara (jangan buat subtitle untuk instrumen hening).
6. Balas HANYA dengan blok format SRT yang valid (00:00:00,000 --> 00:00:00,000) tanpa markdown atau pengantar."""


def parse_srt_string(srt_content: str, offset_seconds: float = 0.0) -> List[SSAEvent]:
    """Parse raw SRT text string into pysubs2 SSAEvents with timestamp offset."""
    cleaned = re.sub(r"^```(?:srt)?\s*", "", srt_content.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    events = []
    # Pattern to match SRT blocks: index, timestamp line, text
    pattern = re.compile(
        r"(\d+)\s*\n"
        r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n"
        r"([\s\S]*?)(?=\n\s*\d+\s*\n|\Z)",
        re.MULTILINE
    )

    offset_ms = int(offset_seconds * 1000)

    def srt_time_to_ms(t_str: str) -> int:
        t_str = t_str.replace(",", ".")
        parts = t_str.split(":")
        h = int(parts[0])
        m = int(parts[1])
        s_parts = parts[2].split(".")
        s = int(s_parts[0])
        ms = int(s_parts[1]) if len(s_parts) > 1 else 0
        return (h * 3600 + m * 60 + s) * 1000 + ms

    for match in pattern.finditer(cleaned):
        start_str = match.group(2)
        end_str = match.group(3)
        text = match.group(4).strip()
        if text:
            start_ms = srt_time_to_ms(start_str) + offset_ms
            end_ms = srt_time_to_ms(end_str) + offset_ms
            events.append(SSAEvent(start=start_ms, end=end_ms, text=text))

    return events


def transcribe_chunk_omniroute_audio(
    chunk_path: Path,
    api_key: str,
    base_url: str = "http://bmnrtkgto-hp:20128/v1",
    model: str = "agy/gemini-3.8-flash-high",
    start_offset: float = 0.0
) -> List[SSAEvent]:
    """
    Direct Audio-to-Indonesian subtitle transcription via Omniroute Multimodal Audio.
    Ultra-fast and produces human-quality fansub subtitles directly from voice.
    """
    with open(chunk_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": FANSUB_AUDIO_PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": "mp3"}
                    }
                ]
            }
        ],
        "temperature": 0.2,
        "safety_settings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"}
        ]
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    with httpx.Client(timeout=300.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        res_data = resp.json()
        raw_content = res_data["choices"][0]["message"]["content"]

    return parse_srt_string(raw_content, offset_seconds=start_offset)


def transcribe_audio_pipeline(
    video_path: Path,
    output_srt_path: Path,
    config: Dict[str, Any],
    chunk_minutes: float = 4.0,
    on_progress: Optional[Callable[[int, int, str], None]] = None
) -> Path:
    """
    End-to-end silence-aware chunked transcription pipeline with checkpoint resume.
    """
    from .chunker import extract_audio_mp3, slice_audio_chunks

    cache_dir = output_srt_path.parent / ".sub_cache" / video_path.stem
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract lightweight master MP3
    master_mp3 = cache_dir / "master_audio.mp3"
    if not master_mp3.exists():
        if on_progress:
            on_progress(0, 100, "Mengekstrak audio vokal MP3...")
        extract_audio_mp3(video_path, master_mp3)

    # Step 2: Slice into silence-aware chunks
    if on_progress:
        on_progress(5, 100, "Mendeteksi titik hening dan memotong segmen audio...")
    chunks = slice_audio_chunks(master_mp3, cache_dir, target_chunk_seconds=chunk_minutes * 60.0)
    total_chunks = len(chunks)

    all_events: List[SSAEvent] = []

    api_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
    base_url = config.get("openai_base_url") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = config.get("openai_model") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    for i, chunk in enumerate(chunks):
        chunk_idx = chunk["index"]
        chunk_file = chunk["path"]
        start_offset = chunk["start"]
        ckpt_file = cache_dir / f"chunk_{chunk_idx:03d}.json"

        if on_progress:
            pct = int(10 + (i / total_chunks) * 85)
            on_progress(pct, 100, f"Mentranskripsikan audio bag. {i+1}/{total_chunks}...")

        if ckpt_file.exists():
            # Resume from checkpoint
            with open(ckpt_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            chunk_events = [SSAEvent(start=item["start"], end=item["end"], text=item["text"]) for item in saved_data]
        else:
            # Transcribe chunk
            chunk_events = transcribe_chunk_omniroute_audio(
                chunk_path=chunk_file,
                api_key=api_key,
                base_url=base_url,
                model=model,
                start_offset=start_offset
            )
            # Save checkpoint
            save_payload = [{"start": ev.start, "end": ev.end, "text": ev.text} for ev in chunk_events]
            with open(ckpt_file, "w", encoding="utf-8") as f:
                json.dump(save_payload, f, ensure_ascii=False, indent=2)

        all_events.extend(chunk_events)

    # Sort events by timestamp
    all_events.sort(key=lambda ev: ev.start)

    subs = SSAFile()
    subs.events = all_events
    subs.info["Title"] = f"Generated by Submaker AI ({video_path.name})"
    subs.save(str(output_srt_path))

    if on_progress:
        on_progress(100, 100, "✔ Subtitle Bahasa Indonesia selesai dibuat!")

    return output_srt_path
