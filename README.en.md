# Local Simultaneous Interpretation Player (EnglishToChinese)

[English](README.en.md) | [中文](README.md) · [Homepage](https://xjalyn.github.io/EnglishToChinese/) · [GitHub](https://github.com/XJALYN/EnglishToChinese)

<p align="center">
  <img src="docs/logo.svg" width="120" height="120" alt="EnglishToChinese logo" />
</p>

Watch English videos from **Bilibili / YouTube** with **local streaming simultaneous interpretation**: ASR → LLM translation → CosyVoice TTS, plus **one-click AI summary**, **mind maps**, and export.

<p align="center">
  <video src="demo.mp4" controls width="720" poster="docs/logo.svg">
    Demo video: local simultaneous interpretation player
  </video>
</p>

<p align="center"><a href="demo.mp4">Download demo video (demo.mp4)</a></p>

## Why not pure Electron?

| Capability | PyQt6 + Python | Pure Electron |
|------------|----------------|---------------|
| Embedded mpv | Native | Needs mpv.js / external window |
| faster-whisper | Mature Python ecosystem | Subprocess or WASM |
| ffmpeg audio split | Direct call | Ship binaries |
| AI panel / settings UI | QWebEngine | Native web UI |

**Architecture**: Python handles playback / ASR / translation / TTS; UI is PyQt6. An **optional Electron frontend** talks to the same Python API.

```
┌─────────────────────────────────────────────────────────┐
│  PyQt6 app (python main.py)                             │
│  ├─ mpv playback + interpretation pipeline               │
│  ├─ Side panel: AI summary | mind map | export          │
│  └─ Visual LLM settings dialog                          │
├─────────────────────────────────────────────────────────┤
│  Optional Electron (cd electron && npm run electron)    │
│  └─ FastAPI backend → settings / summary / mindmap      │
└─────────────────────────────────────────────────────────┘
```

## Features

### Simultaneous interpretation
- Bilibili / YouTube (and similar) URLs → yt-dlp stream → mpv (original audio can be muted)
- Local faster-whisper ASR → LLM translation → CosyVoice TTS
- Live subtitle overlay

### One-click AI summary
- Accumulates bilingual captions while playing
- Calls the LLM for structured Markdown summaries
- Optionally pulls existing Bilibili subtitles as extra context

### Mind maps
- Mermaid mindmaps from captions + summary
- Preview via QWebEngine (`PyQt6-WebEngine`)

### Multi-provider LLM settings
- DashScope / OpenAI / DeepSeek / custom OpenAI-compatible
- Separate models for translate / summary / mindmap
- Persists to `config.json` and syncs `.env` (per-provider keys retained)

### Export
- Summary: Markdown / HTML / JSON
- Mind map: Markdown (with mermaid) / HTML
- Batch “export all” for multiple files

## Install

```bash
pip install -r requirements.txt
brew install mpv ffmpeg
cp .env.example .env   # fill in API keys; may also read ~/.bailian/config.json
```

Requirements:
- **Python 3** (3.10+ recommended)
- **mpv**, **ffmpeg**
- At least one LLM API key (see Configuration)

## Run

### Option A — Full PyQt6 app (recommended, includes video)

```bash
python main.py
```

### Option B — Electron + Python API

```bash
# Terminal 1
python run_api.py

# Terminal 2
cd electron && npm install && npm run electron
```

> Video still plays in the PyQt6 app; Electron focuses on AI settings, summary, and mind maps.

## Configuration

Copy [`.env.example`](https://github.com/XJALYN/EnglishToChinese/blob/main/.env.example) to `.env` and fill in values. **Never commit real secrets.**

### Providers

| Provider | Base URL | Preset models |
|----------|----------|---------------|
| Alibaba DashScope (default) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus, qwen-max, qwen-turbo, qwen-long |
| OpenAI | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini, gpt-4-turbo |
| DeepSeek | `https://api.deepseek.com` | deepseek-chat, deepseek-reasoner |
| Custom OpenAI-compatible | Your URL | Your models |

### Environment variables (from `.env.example`)

| Variable | Meaning | Default |
|----------|---------|---------|
| `LLM_PROVIDER` | `dashscope` / `openai` / `deepseek` / `custom` | `dashscope` |
| `LLM_API_KEY` | Active provider API key | — |
| `LLM_BASE_URL` | Custom base URL | Provider default |
| `DASHSCOPE_API_KEY` | DashScope key (compat) | — |
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | Optional per-provider keys | — |
| `TRANSLATE_MODEL` | Interpretation | `qwen-plus` |
| `SUMMARY_MODEL` | Summary | `qwen-plus` |
| `MINDMAP_MODEL` | Mind map | `qwen-plus` |
| `WHISPER_MODEL` | Local ASR (`tiny` / `base` / `small` / `medium`) | `base` |
| `TTS_VOICE` | CosyVoice voice | `longxiaochun_v3` |
| `HF_ENDPOINT` | HuggingFace mirror | `https://hf-mirror.com` |

You can also open **LLM settings** inside the app.

## API endpoints (FastAPI :8765)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Read settings |
| PUT | `/api/settings` | Update settings |
| GET | `/api/transcript` | Current transcript |
| POST | `/api/summary` | AI summary |
| POST | `/api/mindmap` | Generate mind map |

## Homepage & repository

| Use | URL |
|-----|-----|
| Landing (GitHub Pages) | https://xjalyn.github.io/EnglishToChinese/ |
| Source repo | https://github.com/XJALYN/EnglishToChinese |
| Pages settings | https://github.com/XJALYN/EnglishToChinese/settings/pages |

Preview the landing page locally:

```bash
# from repo root
python -m http.server 8080
# open http://127.0.0.1:8080/
```

## Contributing

Issues and PRs welcome: https://github.com/XJALYN/EnglishToChinese/issues

## License

This project is released under the [GNU General Public License v2.0](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) (GPL-2.0). See [`LICENSE`](https://github.com/XJALYN/EnglishToChinese/blob/main/LICENSE) at the repository root.
