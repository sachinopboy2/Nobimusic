# Warborn Music — container image.
# Everything (ffmpeg + Python deps) installs at build time, so any
# container host (Docker, Podman, Oracle Cloud, Fly, a VPS with Docker)
# gets a ready-to-run bot with zero manual dependency setup.
#
#   docker build -t warborn-music .
#   docker run -d --restart=unless-stopped --name warborn \
#     --env-file .env \
#     -v "$PWD/cookies.txt:/app/cookies.txt:ro" \
#     -v "$PWD/instagram_cookies.txt:/app/instagram_cookies.txt:ro" \
#     warborn-music
#
FROM python:3.13-slim

# System deps: ffmpeg (audio/video), git (for the pinned yt-dlp commit),
# plus build headers for TgCrypto / native wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg git curl ca-certificates build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer-cached unless requirements change).
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip wheel setuptools \
 && python -m pip install --no-cache-dir -r requirements.txt

# App code.
COPY . .

# Unbuffered logs so `docker logs` is live.
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
