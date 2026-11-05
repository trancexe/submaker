# submaker 🎬✨

Anime Subtitle Maker — CLI otomatis untuk membuat dan menerjemahkan takarir (subtitle) anime ke Bahasa Indonesia. Mendukung **video RAW murni (audio Jepang)** maupun **video/subtitle yang sudah ada subtitle bahasa lain (English `.srt`/`.ass`)**.

---

## 🌟 Fitur Utama

1. **Dual Workflow**:
   - **Skenario 1: Sudah ada subtitle (English/Jepang `.srt` / `.ass`)**: Diterjemahkan langsung ke Bahasa Indonesia dengan mempertahankan formatting, tag ASS (seperti miring `{\i1}`, fade, warna), dan timestamp presisi milidetik.
   - **Skenario 2: Video RAW Jepang (tanpa subtitle)**: Pipeline otomatis:
     - Ekstraksi audio vokal 16kHz via `ffmpeg`.
     - Transkripsi suara dialog bahasa Jepang (ASR) via `faster-whisper` (dengan Silero VAD filter agar BGM/lagu tidak terdeteksi jadi dialog ngawur) atau Groq Cloud Whisper API (super cepat).
     - Penerjemahan dialog hasil transkripsi ke Bahasa Indonesia.
     - Menyimpan file `.srt` / `.ass` siap tonton.

2. **Dua Mode Penerjemah**:
   - **Mode Fansub LLM (Direkomendasikan)**: Menggunakan OpenAI-compatible API (OpenAI, OpenRouter, Groq, DeepSeek, Ollama) dengan sistem prompt khusus fansub anime (mempertahankan honorifik *-san, -kun, senpai*, istilah khas jurus, dan gaya bahasa santai/ekspresif ala percakapan manusia).
   - **Mode Bebas Biaya (Google Translate)**: Direct translator HTTP tanpa kuota ketat, cocok untuk menerjemahkan cepat tanpa perlu API Key.

3. **Stream Inspector**: Memeriksa seluruh audio track dan embedded subtitle track yang ada di dalam container video (.mkv, .mp4).

---

## 🚀 Panduan Penggunaan

Jalankan perintah langsung di dalam direktori `submaker`:

### 1. Memeriksa Track Video
```bash
uv run submaker inspect "anime_movie.mkv"
```

### 2. Menerjemahkan Subtitle yang Sudah Ada (.srt / .ass)
Menerjemahkan file subtitle bahasa Inggris atau Jepang yang sudah kamu punya:
```bash
# Menggunakan Google Translate (gratis tanpa API key)
uv run submaker translate "movie_english.srt" --source en

# Menggunakan LLM Fansub Persona
uv run submaker translate "movie_english.ass" --source en --provider llm
```
*Hasil terjemahan akan otomatis disimpan sebagai `<nama_file>.id.srt` atau `<nama_file>.id.ass`.*

---

### 3. Membuat Subtitle dari Video RAW (Murni Audio Jepang)
```bash
# Menggunakan faster-whisper lokal (CPU int8, model medium/small/large-v3)
uv run submaker make-raw "anime_raw.mp4" --model medium

# Jika ingin sangat cepat via Groq Cloud Whisper:
uv run submaker make-raw "anime_raw.mp4" --groq
```

---

## ⚙️ Konfigurasi API (Opsional untuk LLM)

Kamu bisa melihat dan menyetel konfigurasi LLM / Groq API:

```bash
# Cek konfigurasi saat ini
uv run submaker config

# Set LLM Provider (misal OpenRouter atau OpenAI atau Groq)
uv run submaker config --api-key "sk-..." --base-url "https://api.openai.com/v1" --model "gpt-4o-mini"

# Set Groq API key untuk transkripsi kilat
uv run submaker config --groq-key "gsk_..."
```
Atau cukup buat file `.env` di folder `submaker`:
```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
GROQ_API_KEY=gsk-...
```
