"""CLI interface for submaker using Typer and Rich."""

from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from .config import load_config, save_config
from .extractor import list_streams, extract_subtitle_track, extract_audio
from .sub_utils import load_subtitle, save_subtitle
from .transcriber import transcribe_local_whisper, transcribe_groq_whisper
from .translator import translate_subtitles

app = typer.Typer(
    name="submaker",
    help="Anime Subtitle Maker (submaker) - AI Subtitle Extraction, Transcription & Translation CLI ✨",
    add_completion=False
)
console = Console()


@app.command("inspect")
def inspect_media(
    video_path: Path = typer.Argument(..., help="Path to anime video file (e.g., .mkv, .mp4)")
):
    """Inspect audio and embedded subtitle tracks in a video file."""
    if not video_path.exists():
        console.print(f"[bold red]File not found:[/bold red] {video_path}")
        raise typer.Exit(1)

    streams = list_streams(video_path)
    
    table = Table(title=f"Streams in {video_path.name}")
    table.add_column("Type", style="cyan")
    table.add_column("Index", style="magenta")
    table.add_column("Codec", style="green")
    table.add_column("Language", style="yellow")
    table.add_column("Title", style="white")

    for s in streams["audio"]:
        table.add_row("Audio", str(s["index"]), s["codec"], s["language"], s["title"])
    for s in streams["subtitle"]:
        table.add_row("Subtitle", str(s["index"]), s["codec"], s["language"], s["title"])

    console.print(table)


@app.command("translate")
def translate_cmd(
    input_sub: Path = typer.Argument(..., help="Input subtitle file (.srt, .ass, .vtt)"),
    output_sub: Optional[Path] = typer.Option(None, "-o", "--output", help="Output file path"),
    source_lang: str = typer.Option("en", "-s", "--source", help="Source language (e.g., 'en', 'ja')"),
    provider: Optional[str] = typer.Option(None, "-p", "--provider", help="Translation provider: 'llm' or 'google'"),
    batch_size: int = typer.Option(25, "-b", "--batch-size", help="Batch size for translation")
):
    """Translate an existing subtitle file (.srt / .ass) to Indonesian."""
    if not input_sub.exists():
        console.print(f"[bold red]Subtitle not found:[/bold red] {input_sub}")
        raise typer.Exit(1)

    if not output_sub:
        suffix = input_sub.suffix
        output_sub = input_sub.with_name(f"{input_sub.stem}.id{suffix}")

    cfg = load_config()
    chosen_provider = provider or cfg.get("provider", "google")

    console.print(f"[bold cyan]✨ Loading subtitle:[/bold cyan] {input_sub.name}")
    subs = load_subtitle(input_sub)
    console.print(f"Total lines: [green]{len(subs)}[/green] | Provider: [yellow]{chosen_provider.upper()}[/yellow]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task(f"Translating to Indonesian ({source_lang} -> id)...", total=len(subs))

        def update_progress(current, total):
            progress.update(task, completed=current, total=total)

        translated = translate_subtitles(
            subs=subs,
            provider=chosen_provider,
            api_key=cfg.get("openai_api_key"),
            base_url=cfg.get("openai_base_url"),
            model=cfg.get("openai_model"),
            source_lang=source_lang,
            batch_size=batch_size,
            on_progress=update_progress
        )

    save_subtitle(translated, output_sub)
    console.print(f"[bold green]✔ Selesai![/bold green] Subtitle tersimpan di: [bold yellow]{output_sub}[/bold yellow] (≧∇≦)/")


@app.command("make-raw")
def make_raw_cmd(
    video_path: Path = typer.Argument(..., help="Path to raw anime video file"),
    output_sub: Optional[Path] = typer.Option(None, "-o", "--output", help="Output subtitle path (.srt or .ass)"),
    model_size: str = typer.Option("medium", "-m", "--model", help="Whisper model size (base, small, medium, large-v3)"),
    provider: Optional[str] = typer.Option(None, "-p", "--provider", help="Translation provider: 'llm' or 'google'"),
    use_groq: bool = typer.Option(False, "--groq", help="Use Groq Cloud Whisper API for super-fast transcription")
):
    """Generate Indonesian subtitle from a RAW Japanese anime video (ASR + Translation)."""
    if not video_path.exists():
        console.print(f"[bold red]Video not found:[/bold red] {video_path}")
        raise typer.Exit(1)

    if not output_sub:
        output_sub = video_path.with_name(f"{video_path.stem}.id.srt")

    cfg = load_config()
    chosen_provider = provider or cfg.get("provider", "google")
    temp_wav = video_path.with_name(f"{video_path.stem}_temp_audio.wav")

    try:
        # Step 1: Audio Extraction
        console.print(f"[bold cyan]1/3 Mengekstrak audio vokal 16kHz mono...[/bold cyan]")
        extract_audio(video_path, temp_wav)

        # Step 2: Speech-to-Text Transcription
        console.print(f"[bold cyan]2/3 Transkripsi suara dialog Jepang (ASR)...[/bold cyan]")
        if use_groq:
            console.print("[yellow]Menggunakan Groq Cloud Whisper API...[/yellow]")
            subs_ja = transcribe_groq_whisper(temp_wav, api_key=cfg.get("groq_api_key"))
        else:
            console.print(f"[yellow]Menggunakan faster-whisper lokal ({model_size}, CPU int8)...[/yellow]")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=console
            ) as progress:
                task = progress.add_task("Transcribing Japanese speech...", total=100)
                
                def on_transcribe_progress(pct, text):
                    progress.update(task, completed=int(pct * 100))

                subs_ja = transcribe_local_whisper(
                    temp_wav,
                    model_size=model_size,
                    language="ja",
                    device=cfg.get("whisper_device", "cpu"),
                    compute_type=cfg.get("whisper_compute_type", "int8"),
                    on_progress=on_transcribe_progress
                )

        console.print(f"Total baris terdeteksi: [green]{len(subs_ja)}[/green]")
        
        # Save raw Japanese transcription for reference
        raw_ja_file = video_path.with_name(f"{video_path.stem}.ja.srt")
        save_subtitle(subs_ja, raw_ja_file)
        console.print(f"[dim]Takarir Jepang mentah disimpan di: {raw_ja_file.name}[/dim]")

        # Step 3: Translation
        console.print(f"[bold cyan]3/3 Menerjemahkan dialog Jepang ke Bahasa Indonesia alami...[/bold cyan]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task(f"Translating to Indonesian ({chosen_provider})...", total=len(subs_ja))

            def on_trans_progress(cur, tot):
                progress.update(task, completed=cur, total=tot)

            subs_id = translate_subtitles(
                subs=subs_ja,
                provider=chosen_provider,
                api_key=cfg.get("openai_api_key"),
                base_url=cfg.get("openai_base_url"),
                model=cfg.get("openai_model"),
                source_lang="ja",
                on_progress=on_trans_progress
            )

        save_subtitle(subs_id, output_sub)
        console.print(f"[bold green]✔ Selesai sepenuhnya![/bold green] File subtitle: [bold yellow]{output_sub}[/bold yellow] (≧∇≦)b")

    finally:
        # Cleanup temporary audio
        if temp_wav.exists():
            temp_wav.unlink()


@app.command("gui")
def gui_cmd(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host interface to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to run the Web GUI")
):
    """Launch the interactive Submaker Studio Web GUI! ✨"""
    import uvicorn
    console.print(f"[bold cyan]🚀 Menjalankan Submaker Studio Web GUI...[/bold cyan]")
    console.print(f"[bold green]Akses di browser:[/bold green] [bold yellow]http://{host}:{port}[/bold yellow] (≧∇≦)/")
    uvicorn.run("submaker.server:app", host=host, port=port, reload=False)


@app.command("config")
def config_cmd(
    set_provider: Optional[str] = typer.Option(None, "--provider", help="Set default provider ('google' or 'llm')"),
    set_api_key: Optional[str] = typer.Option(None, "--api-key", help="Set OpenAI/OpenRouter API key"),
    set_base_url: Optional[str] = typer.Option(None, "--base-url", help="Set OpenAI-compatible Base URL"),
    set_model: Optional[str] = typer.Option(None, "--model", help="Set LLM Model (e.g. gpt-4o-mini, gemini-2.0-flash, claude-3-5-haiku)"),
    set_groq_key: Optional[str] = typer.Option(None, "--groq-key", help="Set Groq API key for instant whisper")
):
    """View or update submaker configuration."""
    cfg = load_config()

    changed = False
    if set_provider:
        cfg["provider"] = set_provider
        changed = True
    if set_api_key:
        cfg["openai_api_key"] = set_api_key
        changed = True
    if set_base_url:
        cfg["openai_base_url"] = set_base_url
        changed = True
    if set_model:
        cfg["openai_model"] = set_model
        changed = True
    if set_groq_key:
        cfg["groq_api_key"] = set_groq_key
        changed = True

    if changed:
        save_config(cfg)
        console.print("[bold green]✔ Konfigurasi berhasil diperbarui![/bold green]")

    # Display current config (mask keys)
    table = Table(title="Konfigurasi submaker Aktif")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="yellow")

    for k, v in cfg.items():
        if "key" in k.lower() and v:
            masked = v[:6] + "..." + v[-4:] if len(v) > 10 else "***"
            table.add_row(k, masked)
        else:
            table.add_row(k, str(v))

    console.print(table)


def main():
    app()


if __name__ == "__main__":
    main()
