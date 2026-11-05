"""Translation engine supporting multiple providers:
1. LLM (OpenAI-compatible: OpenRouter, OpenAI, Groq, Ollama, DeepSeek) with specialized anime fansub prompt.
2. Free fallback via Google Translate (deep-translator).
"""

import json
import os
import re
from typing import List, Dict, Optional, Callable
import httpx
from deep_translator import GoogleTranslator
from pysubs2 import SSAFile, SSAEvent

from .sub_utils import events_to_batches

ANIME_FANSUB_SYSTEM_PROMPT = """Kamu adalah penerjemah takarir (fansub translator) anime berpengalaman ke Bahasa Indonesia.
Tugasmu adalah menerjemahkan baris dialog anime dari bahasa sumber ke Bahasa Indonesia alami, luwes, dan kontekstual.

Aturan Penting:
1. **Bahasa Alami & Ekspresif**: Jangan menerjemahkan kata-per-kata secara kaku seperti mesin. Gunakan dialog yang enak didengar dan dibaca oleh penonton Indonesia, sesuaikan dengan kepribadian karakter (santai, kasar, sopan/formal, imut, dll).
2. **Honorifik & Istilah Khas Anime**:
   - Pertahankan honorifik Jepang jika cocok dengan nuansa karakter (-san, -kun, -chan, -senpai, -sama, sensei).
   - Istilah jurus, nama teknik, nama tempat, dan nama karakter jangan diterjemahkan ke bahasa Indonesia harfiah jika memang merupakan istilah khas.
3. **Format Konsisten**:
   - Kamu akan menerima list JSON berisi ID dan teks dialog: `[{"id": 0, "text": "..."}, ...]`.
   - Wajib balas HANYA dengan list JSON berformat persis sama: `[{"id": 0, "text": "Terjemahan Indonesia"}, ...]`.
   - Pertahankan tag formatting (seperti {\\i1}...{\\i0} atau tanda baris baru \\N jika ada).
   - Jangan menambahkan markdown pembuka/penutup selain valid JSON array, jangan berikan penjelasan pengantar.
"""


def translate_batch_llm(
    items: List[Dict[str, any]],
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    source_lang: str = "ja"
) -> Dict[int, str]:
    """Translate a batch of subtitle lines using an OpenAI-compatible API."""
    prompt = (
        f"Terjemahkan dialog anime berikut dari {source_lang} ke Bahasa Indonesia yang luwes dan alami:\n"
        f"{json.dumps(items, ensure_ascii=False)}"
    )

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": ANIME_FANSUB_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }

    resp = httpx.post(url, headers=headers, json=payload, timeout=90.0)
    resp.raise_for_status()
    raw_content = resp.json()["choices"][0]["message"]["content"].strip()

    # Clean markdown backticks if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_content)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        translated_list = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback regex parsing if JSON is slightly dirty
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            translated_list = json.loads(match.group(0))
        else:
            raise ValueError(f"Failed to parse LLM response as JSON: {raw_content[:200]}")

    results = {}
    for item in translated_list:
        results[item["id"]] = item["text"]
    return results


def translate_batch_google(items: List[Dict[str, any]], source_lang: str = "auto") -> Dict[int, str]:
    """Fallback translator using Google Translate HTTP API directly with high reliability."""
    s_lang = source_lang if source_lang not in ["auto", "und"] else "auto"
    
    results = {}
    with httpx.Client(timeout=15.0) as client:
        for item in items:
            text = item["text"]
            if not text.strip():
                results[item["id"]] = text
                continue
            
            # Extract HTML/font tags if present so we only translate the inner text
            # e.g. <font color="...">text</font>
            tag_prefix_match = re.match(r"^((?:<font[^>]*>)+)", text)
            tag_suffix_match = re.search(r"((?:</font>)+)$", text)
            
            prefix = tag_prefix_match.group(1) if tag_prefix_match else ""
            suffix = tag_suffix_match.group(1) if tag_suffix_match else ""
            
            clean_text = text
            if prefix:
                clean_text = clean_text[len(prefix):]
            if suffix:
                clean_text = clean_text[:-len(suffix)]
                
            try:
                # Direct endpoint used by lightweight translation clients
                url = "https://translate.googleapis.com/translate_a/single"
                params = {
                    "client": "gtx",
                    "sl": s_lang,
                    "tl": "id",
                    "dt": "t",
                    "q": clean_text
                }
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    # data[0] contains list of translated sentences
                    translated_pieces = [piece[0] for piece in data[0] if piece and piece[0]]
                    translated_text = "".join(translated_pieces)
                    results[item["id"]] = f"{prefix}{translated_text}{suffix}"
                else:
                    results[item["id"]] = text
            except Exception:
                results[item["id"]] = text
    return results


def translate_subtitles(
    subs: SSAFile,
    provider: str = "google",
    api_key: Optional[str] = None,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    source_lang: str = "ja",
    batch_size: int = 30,
    on_progress: Optional[Callable[[int, int], None]] = None
) -> SSAFile:
    """
    Translates an SSAFile into Indonesian, preserving styles and timestamps.
    Returns a new SSAFile with translated text.
    Uses concurrent workers for LLM translation to speed up processing significantly.
    """
    import copy
    from concurrent.futures import ThreadPoolExecutor, as_completed

    new_subs = copy.deepcopy(subs)
    batches = events_to_batches(new_subs, batch_size=batch_size)
    total_events = sum(len(b) for b in batches)
    processed = 0

    if provider == "llm":
        if not api_key:
            raise ValueError("API key is required for LLM translation.")

        def _do_batch(b):
            items = [{"id": idx, "text": ev.text} for idx, ev in b]
            return b, translate_batch_llm(
                items=items,
                api_key=api_key,
                base_url=base_url,
                model=model,
                source_lang=source_lang
            )

        # Use 3 concurrent workers to speed up batch processing without overloading local LLM
        max_workers = 3
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {executor.submit(_do_batch, b): b for b in batches}
            for future in as_completed(future_to_batch):
                batch, translated_dict = future.result()
                for idx, ev in batch:
                    if idx in translated_dict:
                        ev.text = translated_dict[idx]
                processed += len(batch)
                if on_progress:
                    on_progress(processed, total_events)
    else:
        for batch in batches:
            items = [{"id": idx, "text": ev.text} for idx, ev in batch]
            translated_dict = translate_batch_google(items=items, source_lang=source_lang)
            for idx, ev in batch:
                if idx in translated_dict:
                    ev.text = translated_dict[idx]
            processed += len(batch)
            if on_progress:
                on_progress(processed, total_events)

    return new_subs
