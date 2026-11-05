"""Audio extraction, silence-aware chunking, and checkpoint management for long media files."""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any

log = logging.getLogger("submaker.chunker")


def get_media_duration(file_path: str | Path) -> float:
    """Get duration of media file in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def extract_audio_mp3(video_path: str | Path, output_mp3: str | Path) -> Path:
    """
    Extract audio track to mono 64kbps MP3.
    Highly optimized for speech recognition: ~0.5 MB per minute, well below 25MB limits.
    """
    output_mp3 = Path(output_mp3)
    output_mp3.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "64k",
        str(output_mp3)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return output_mp3


def find_silence_points(
    audio_path: str | Path,
    noise_db: int = -30,
    min_duration: float = 0.4
) -> List[Tuple[float, float]]:
    """
    Find silence intervals in audio using ffmpeg silencedetect.
    Returns a list of (silence_start, silence_end) in seconds.
    """
    cmd = [
        "ffmpeg",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f", "null",
        "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    stderr = res.stderr

    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*([0-9.]+)", stderr)]

    intervals = []
    for s in starts:
        # Find closest end after start
        matching_ends = [e for e in ends if e >= s]
        if matching_ends:
            intervals.append((s, matching_ends[0]))
        else:
            intervals.append((s, s + min_duration))

    return intervals


def calculate_split_points(
    total_duration: float,
    silence_intervals: List[Tuple[float, float]],
    target_chunk_seconds: float = 240.0,  # 4 minutes optimal for multimodal audio context
    window_seconds: float = 20.0          # +/- 20s around target
) -> List[float]:
    """
    Calculate optimal cut points preferring silence intervals within target windows.
    """
    if total_duration <= target_chunk_seconds * 1.15:
        return [total_duration]

    split_points = []
    current_time = 0.0

    while current_time + target_chunk_seconds < total_duration:
        target_time = current_time + target_chunk_seconds
        window_start = max(current_time + 30.0, target_time - window_seconds)
        window_end = min(total_duration - 30.0, target_time + window_seconds)

        # Look for silence in window
        candidates = [
            (s + e) / 2.0
            for s, e in silence_intervals
            if window_start <= ((s + e) / 2.0) <= window_end
        ]

        if candidates:
            # Pick silence midpoint closest to target_time
            best_cut = min(candidates, key=lambda c: abs(c - target_time))
        else:
            # Fallback: cut at exact target_time
            best_cut = target_time

        split_points.append(best_cut)
        current_time = best_cut

    if not split_points or split_points[-1] < total_duration:
        split_points.append(total_duration)

    return split_points


def slice_audio_chunks(
    audio_path: str | Path,
    output_dir: str | Path,
    target_chunk_seconds: float = 240.0
) -> List[Dict[str, Any]]:
    """
    Extracts and slices audio into silence-guided chunks.
    Returns list of dicts:
    [
        {"index": 0, "path": Path, "start": 0.0, "end": 598.2, "duration": 598.2},
        ...
    ]
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_duration = get_media_duration(audio_path)
    if total_duration <= target_chunk_seconds * 1.1:
        # Single chunk is sufficient
        single_chunk = output_dir / f"{audio_path.stem}_part_000.mp3"
        if not single_chunk.exists():
            import shutil
            shutil.copy2(audio_path, single_chunk)
        return [{
            "index": 0,
            "path": single_chunk,
            "start": 0.0,
            "end": total_duration,
            "duration": total_duration
        }]

    silence_intervals = find_silence_points(audio_path)
    split_points = calculate_split_points(total_duration, silence_intervals, target_chunk_seconds)

    chunks = []
    prev_point = 0.0

    for idx, cut_point in enumerate(split_points):
        dur = cut_point - prev_point
        chunk_file = output_dir / f"{audio_path.stem}_part_{idx:03d}.mp3"

        if not chunk_file.exists():
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{prev_point:.3f}",
                "-i", str(audio_path),
                "-t", f"{dur:.3f}",
                "-c", "copy",
                str(chunk_file)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        chunks.append({
            "index": idx,
            "path": chunk_file,
            "start": prev_point,
            "end": cut_point,
            "duration": dur
        })
        prev_point = cut_point

    return chunks
