# VidSubKh — Setup Guide

## Prerequisites

Install these before running VidSubKh:

### 1. Node.js & npm
Download from https://nodejs.org (v18+)

### 2. Python 3.10+
Download from https://python.org

### 3. FFmpeg
- **Windows**: Download from https://ffmpeg.org and add to PATH
- **Mac**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### 4. yt-dlp
```bash
pip install yt-dlp
```

### 5. Python AI libraries
```bash
pip install openai \
            google-cloud-translate \
            elevenlabs \
            moviepy \
            pydub \
            deepfilternet \
            demucs \
            srt
```

---

## Installation

```bash
# Clone or unzip the project
cd VidSubKh

# Install Node dependencies
npm install

# Run in development mode
npm start

# Build desktop app
npm run build:win     # Windows (.exe installer)
npm run build:mac     # macOS (.dmg)
npm run build:linux   # Linux (.AppImage)
```

---

## API Keys (required for AI Translator)

Open **Settings** in the app and enter:

| Service | Where to get |
|---|---|
| OpenAI API Key | https://platform.openai.com/api-keys |
| Google Cloud credentials JSON | https://console.cloud.google.com → Service Accounts |
| ElevenLabs API Key | https://elevenlabs.io → Profile → API Keys |

---

## AI Services Used

| Feature | Service | Cost |
|---|---|---|
| Transcription | OpenAI Whisper | ~$0.006/min |
| Translation | Google Cloud Translation | ~$20/1M chars |
| Voice synthesis | ElevenLabs | From $5/mo |
| Lip Sync | Wav2Lip (open source) | Free |
| Noise removal | DeepFilterNet (open source) | Free |
| Music separation | Demucs (open source) | Free |
| Downloading | yt-dlp (open source) | Free |

---

## Project Structure

```
VidSubKh/
├── src/
│   ├── main/
│   │   ├── main.js          # Electron main process
│   │   └── preload.js       # Secure IPC bridge
│   └── renderer/
│       ├── index.html       # App shell
│       ├── app.js           # Tab router
│       ├── styles/
│       │   └── main.css     # Full stylesheet
│       └── pages/
│           ├── downloader.js  # YouTube downloader UI
│           ├── translator.js  # AI translator UI
│           └── settings.js    # Settings UI
├── python/
│   ├── downloader.py        # yt-dlp wrapper
│   └── translator.py        # AI pipeline (Whisper → Translate → ElevenLabs)
├── package.json
└── README.md
```
