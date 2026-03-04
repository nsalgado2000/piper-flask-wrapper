#!/usr/bin/env python3
"""
Piper TTS HTTP server - OpenAI-compatible /v1/audio/speech endpoint

Voices are configured via voices.json. See README for setup instructions.
"""

import json
import os
import subprocess
import tempfile

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

PIPER_BIN = os.environ.get("PIPER_BIN", "piper-tts")
ESPEAK_DATA = os.environ.get("ESPEAK_DATA", "")

# Load voices from voices.json (or PIPER_VOICES_JSON env var)
# Format: {"voice_name": "/path/to/model.onnx", ...}
_voices_path = os.environ.get("PIPER_VOICES_JSON", os.path.join(os.path.dirname(__file__), "voices.json"))
if not os.path.exists(_voices_path):
    raise RuntimeError(
        f"voices.json not found at {_voices_path}. "
        "Create it or set PIPER_VOICES_JSON. See README for details."
    )

with open(_voices_path) as f:
    VOICES = json.load(f)

DEFAULT_VOICE = os.environ.get("PIPER_DEFAULT_VOICE", next(iter(VOICES)))


def synthesize(text: str, voice: str) -> bytes:
    model_path = VOICES.get(voice, VOICES[DEFAULT_VOICE])
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", tmp_path, "--quiet"]
        if ESPEAK_DATA:
            cmd += ["--espeak_data", ESPEAK_DATA]

        proc = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode())

        # Resample to 24000 Hz (expected by OpenAI-compatible clients)
        resampled = tmp_path + "_24k.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-ar", "24000", resampled],
            capture_output=True, check=True,
        )
        with open(resampled, "rb") as f:
            return f.read()
    finally:
        for p in [tmp_path, tmp_path + "_24k.wav"]:
            if os.path.exists(p):
                os.unlink(p)


@app.route("/v1/audio/speech", methods=["POST"])
def speech():
    data = request.get_json(force=True)
    text = data.get("input", "")
    voice = data.get("voice", DEFAULT_VOICE).lower()

    if not text:
        return jsonify({"error": "input is required"}), 400

    # Fall back to default for unknown voice names (e.g. OpenAI built-ins)
    if voice not in VOICES:
        voice = DEFAULT_VOICE

    print(f"[TTS] voice={voice!r} text={text[:60]!r}")
    try:
        audio = synthesize(text, voice)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return Response(audio, mimetype="audio/wav")


@app.route("/v1/models", methods=["GET"])
def models():
    return jsonify({"object": "list", "data": [{"id": "tts-1", "object": "model"}]})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "voices": list(VOICES.keys()), "default": DEFAULT_VOICE})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8880)))
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    args = parser.parse_args()
    print(f"Piper TTS server running on {args.host}:{args.port}")
    print(f"Voices: {', '.join(VOICES.keys())} (default: {DEFAULT_VOICE})")
    app.run(host=args.host, port=args.port)
