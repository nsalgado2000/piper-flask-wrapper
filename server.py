#!/usr/bin/env python3
"""
Piper TTS HTTP server - OpenAI-compatible /v1/audio/speech endpoint

Voices are configured via voices.json. See README for setup instructions.
"""

import json
import os
import re
import subprocess
import tempfile

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

PIPER_BIN = os.environ.get("PIPER_BIN", "piper-tts")
ESPEAK_DATA = os.environ.get("ESPEAK_DATA", "")

# Load voices from voices.json (or PIPER_VOICES_JSON env var)
_voices_path = os.environ.get("PIPER_VOICES_JSON", os.path.join(os.path.dirname(__file__), "voices.json"))
if not os.path.exists(_voices_path):
    raise RuntimeError(
        f"voices.json not found at {_voices_path}. "
        "Create it or set PIPER_VOICES_JSON. See README for details."
    )

with open(_voices_path) as f:
    VOICES = json.load(f)

DEFAULT_VOICE = os.environ.get("PIPER_DEFAULT_VOICE", next(iter(VOICES)))


def split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunk streaming."""
    sentences = re.split(r'(?<=[.!?,;:])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def synthesize_pcm(text: str, model_path: str) -> bytes:
    """Synthesize a single chunk of text and return raw PCM at 24000 Hz."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    raw_path = tmp_path + ".raw"

    try:
        cmd = [PIPER_BIN, "--model", model_path, "--output_file", tmp_path, "--quiet"]
        if ESPEAK_DATA:
            cmd += ["--espeak_data", ESPEAK_DATA]

        proc = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode())

        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-ar", "24000", "-ac", "1", "-f", "s16le", raw_path],
            capture_output=True, check=True,
        )
        with open(raw_path, "rb") as f:
            return f.read()
    finally:
        for p in [tmp_path, raw_path]:
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

    model_path = VOICES[voice]
    print(f"[TTS] voice={voice!r} text={text[:60]!r}")

    sentences = split_sentences(text)

    def generate():
        for sentence in sentences:
            try:
                yield synthesize_pcm(sentence, model_path)
            except Exception as e:
                print(f"[TTS] error on sentence: {e}")

    return Response(generate(), mimetype="audio/pcm")


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
