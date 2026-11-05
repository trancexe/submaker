"""Media extraction utilities using ffmpeg and ffprobe."""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any


def probe_file(file_path: str | Path) -> Dict[str, Any]:
    """Run ffprobe to get stream information for video/audio/subtitles."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def list_streams(file_path: str | Path) -> Dict[str, List[Dict[str, Any]]]:
    """List audio and subtitle streams available in the file."""
    data = probe_file(file_path)
    streams = data.get("streams", [])
    
    result = {"audio": [], "subtitle": []}
    for s in streams:
        c_type = s.get("codec_type")
        if c_type in result:
            tags = s.get("tags", {})
            lang = tags.get("language", "und")
            title = tags.get("title", "")
            codec = s.get("codec_name", "")
            index = s.get("index")
            result[c_type].append({
                "index": index,
                "codec": codec,
                "language": lang,
                "title": title
            })
    return result


def extract_subtitle_track(video_path: str | Path, track_index: int, output_path: str | Path) -> Path:
    """Extract an embedded subtitle track to an external file (e.g., .ass or .srt)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-map", f"0:{track_index}",
        str(output_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return output_path


def extract_audio(video_path: str | Path, output_wav: str | Path, audio_stream_index: int | None = None) -> Path:
    """Extract audio track converted to 16kHz mono WAV, optimal for Whisper."""
    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = ["ffmpeg", "-y", "-i", str(video_path)]
    if audio_stream_index is not None:
        cmd.extend(["-map", f"0:{audio_stream_index}"])
    else:
        cmd.extend(["-vn"])  # disable video, takes first audio stream
        
    cmd.extend([
        "-ac", "1",           # mono
        "-ar", "16000",       # 16kHz
        "-c:a", "pcm_s16le",  # uncompressed PCM 16-bit
        str(output_wav)
    ])
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return output_wav
