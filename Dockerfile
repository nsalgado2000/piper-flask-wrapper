FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install piper-tts binary
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) PIPER_ARCH="x86_64" ;; \
      arm64) PIPER_ARCH="aarch64" ;; \
      *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -L "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_${PIPER_ARCH}.tar.gz" \
      -o /tmp/piper.tar.gz && \
    tar -xzf /tmp/piper.tar.gz -C /opt && \
    rm /tmp/piper.tar.gz

ENV PIPER_BIN=/opt/piper/piper
ENV ESPEAK_DATA=/opt/piper/espeak-ng-data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY models/ ./models/
COPY voices.docker.json ./voices.json

ENV PIPER_VOICES_JSON=/app/voices.json
ENV PIPER_DEFAULT_VOICE=dii
ENV PIPER_LANG_VOICES='{"pt": "dii", "en": "ljspeech"}'
ENV HOST=0.0.0.0
ENV PORT=8880

EXPOSE 8880

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8880/health || exit 1

CMD ["python", "server.py"]
