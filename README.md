# piper-flask-wrapper

An OpenAI-compatible HTTP server that wraps [Piper TTS](https://github.com/rhasspy/piper), exposing a `/v1/audio/speech` endpoint compatible with tools like [VoiceMode](https://github.com/mbailey/voicemode).

## Requirements

- Python 3.8+
- [piper-tts](https://github.com/rhasspy/piper) binary available in PATH (or set `PIPER_BIN`)
- [ffmpeg](https://ffmpeg.org/) for audio resampling
- Flask (`pip install flask`)

## Setup

1. Download Piper voice models (.onnx) from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)

2. Create a `voices.json` file based on `voices.json.example`:
```json
{
  "ljspeech": "/path/to/en_US-ljspeech-high.onnx",
  "lessac": "/path/to/en_US-lessac-medium.onnx"
}
```

3. Run the server:
```bash
python server.py
```

## Configuration

All configuration is done via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PIPER_BIN` | `piper-tts` | Path to piper binary |
| `ESPEAK_DATA` | _(empty)_ | Path to espeak-ng data dir (required for some installations) |
| `PIPER_VOICES_JSON` | `voices.json` | Path to voices config file |
| `PIPER_DEFAULT_VOICE` | first voice in voices.json | Default voice name |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8880` | Server port |

### Example with custom espeak data (e.g. paru/AUR install):

```bash
ESPEAK_DATA=/opt/piper-tts/espeak-ng-data python server.py
```

## Endpoints

- `POST /v1/audio/speech` — Generate speech (OpenAI-compatible)
- `GET /v1/models` — List available models
- `GET /health` — Health check, lists loaded voices

## Systemd user service

Create `~/.config/systemd/user/piper-tts.service`:

```ini
[Unit]
Description=Piper TTS HTTP Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/server.py
Environment=PIPER_BIN=/usr/bin/piper-tts
Environment=ESPEAK_DATA=/opt/piper-tts/espeak-ng-data
Environment=PIPER_VOICES_JSON=/path/to/voices.json
Environment=PIPER_DEFAULT_VOICE=ljspeech
Restart=on-failure

[Install]
WantedBy=default.target
```

Then:
```bash
systemctl --user enable --now piper-tts.service
```

## VoiceMode integration

Add to `~/.voicemode/voicemode.env`:

```env
VOICEMODE_TTS_BASE_URLS=http://127.0.0.1:8880/v1
VOICEMODE_TTS_AUDIO_FORMAT=wav
```
