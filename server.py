#!/usr/bin/env python3
"""
Piper TTS HTTP server - OpenAI-compatible /v1/audio/speech endpoint

Voices are configured via voices.json. See README for setup instructions.

Language auto-detection: when the caller sends an unknown voice name (e.g. OpenAI
built-ins like "alloy"), the server detects the input language via pattern matching
and maps it to a configured voice. Override the mapping via PIPER_LANG_VOICES env
var as a JSON object, e.g. '{"pt": "dii", "en": "ljspeech"}'.
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

# Language-to-voice mapping used when voice auto-detection is triggered.
# Override via PIPER_LANG_VOICES env var as JSON, e.g. '{"pt": "dii", "en": "ljspeech"}'.
_lang_voices_env = os.environ.get("PIPER_LANG_VOICES", "")
LANG_VOICES: dict[str, str] = json.loads(_lang_voices_env) if _lang_voices_env else {"pt": "dii", "en": "ljspeech"}

# Patterns for heuristic language detection (Portuguese vs English).
# Portuguese is identified by accented characters and common function words.
_PT_PATTERN = re.compile(
    r"[ãõâêôáéíóúàüç]|"
    r"\b(não|que|para|com|uma|isso|mas|por|mais|como|ele|ela|seu|sua|são|também|muito|sobre|entre|quando|então|ainda|onde|aqui|já|você|nos|se|ao|da|do|das|dos|num|numa)\b",
    re.IGNORECASE,
)
_EN_PATTERN = re.compile(
    r"\b(the|is|are|was|were|this|that|with|have|has|will|would|could|should|from|they|their|there|been|being|which|what|when|where|your|you|our|we|it|its|not|but|and|for|can|may|just|an|be|by|or|at|on|in|to|of|a)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Detect whether text is Portuguese or English using pattern matching.

    Returns 'pt', 'en', or 'unknown' if no patterns match.
    """
    pt_score = len(_PT_PATTERN.findall(text))
    en_score = len(_EN_PATTERN.findall(text))
    if pt_score == 0 and en_score == 0:
        return "unknown"
    return "pt" if pt_score >= en_score else "en"


def split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunk streaming."""
    sentences = re.split(r'(?<=[.!?,;:])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def synthesize_pcm(text: str, model_path: str, speed: float = 1.0) -> bytes:
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

        # atempo supports 0.5-2.0; chain filters for values outside that range
        speed = max(0.25, min(speed, 4.0))
        atempo_filters = []
        remaining = speed
        while remaining > 2.0:
            atempo_filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            atempo_filters.append("atempo=0.5")
            remaining /= 0.5
        atempo_filters.append(f"atempo={remaining:.4f}")
        af = ",".join(atempo_filters)

        ffmpeg_cmd = ["ffmpeg", "-y", "-i", tmp_path, "-af", af, "-ar", "24000", "-ac", "1", "-f", "s16le", raw_path]
        subprocess.run(ffmpeg_cmd, capture_output=True, check=True)
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
    speed = float(data.get("speed", 1.0))

    if not text:
        return jsonify({"error": "input is required"}), 400

    # Auto-detect language and pick voice when caller sends an unknown voice name
    # (e.g. OpenAI built-ins like "alloy" that don't exist in voices.json).
    if voice not in VOICES:
        lang = detect_language(text)
        voice = LANG_VOICES.get(lang, DEFAULT_VOICE)
        print(f"[TTS] auto-detected lang={lang!r} -> voice={voice!r}")

    model_path = VOICES[voice]
    print(f"[TTS] voice={voice!r} speed={speed} text={text[:60]!r}")

    sentences = split_sentences(text)

    def generate():
        for sentence in sentences:
            try:
                yield synthesize_pcm(sentence, model_path, speed=speed)
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
