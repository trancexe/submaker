"""Subtitle utilities using pysubs2 for parsing, formatting, and tag handling."""

from pathlib import Path
from typing import List, Tuple
import pysubs2
from pysubs2 import SSAFile, SSAEvent


def load_subtitle(path: str | Path) -> SSAFile:
    """Load subtitle from file (supports .srt, .ass, .ssa, .vtt)."""
    return pysubs2.load(str(path))


def save_subtitle(subs: SSAFile, output_path: str | Path, format: str | None = None) -> None:
    """Save subtitle to file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output_path), format_=format)


def extract_clean_text(event_text: str) -> Tuple[str, List[str]]:
    """
    Separates pysubs2 event text into clean translatable text and formatting tags.
    Handles ASS tags like {\\fad(200,200)}, {\\an8}, {\\i1}...{\\i0}.
    Replaces newlines with spaces or maintains simple linebreaks.
    """
    # pysubs2 already handles some tags, but for translation, we want raw clean text
    # In ASS, \N is hard linebreak, \n is soft linebreak
    clean = event_text.replace(r"\N", "\n").replace(r"\n", " ")
    
    # Simple tag stripper or placeholder
    # For now, let's clean leading/trailing tags
    return clean.strip()


def events_to_batches(subs: SSAFile, batch_size: int = 30) -> List[List[Tuple[int, SSAEvent]]]:
    """Group non-empty dialogue subtitle events into batches for LLM/API efficiency."""
    dialogue_events = []
    for idx, ev in enumerate(subs):
        # Skip empty lines or pure drawing/comments
        text = ev.text.strip()
        if text and not ev.is_comment:
            dialogue_events.append((idx, ev))
            
    batches = []
    for i in range(0, len(dialogue_events), batch_size):
        batches.append(dialogue_events[i:i + batch_size])
    return batches
