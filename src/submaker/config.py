"""Configuration loader and manager for submaker."""

import os
import json
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".config" / "submaker"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Load local .env if present
load_dotenv()


def get_default_config() -> Dict[str, Any]:
    return {
        "provider": "google",  # 'google' or 'llm'
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "whisper_model": "medium",  # tiny, base, small, medium, large-v3
        "whisper_device": "cpu",
        "whisper_compute_type": "int8"
    }


def load_config() -> Dict[str, Any]:
    cfg = get_default_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass
            
    # Environment variables override config file
    if os.getenv("OPENAI_API_KEY"):
        cfg["openai_api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("OPENAI_BASE_URL"):
        cfg["openai_base_url"] = os.getenv("OPENAI_BASE_URL")
    if os.getenv("OPENAI_MODEL"):
        cfg["openai_model"] = os.getenv("OPENAI_MODEL")
    if os.getenv("GROQ_API_KEY"):
        cfg["groq_api_key"] = os.getenv("GROQ_API_KEY")

    # Auto switch provider to llm if API key is present and not explicitly set
    if cfg["openai_api_key"] and cfg.get("provider") == "google":
        cfg["provider"] = "llm"

    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
