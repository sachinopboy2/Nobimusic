#!/usr/bin/env bash
#
# One-shot bootstrap for Warborn Music.
#
#   bash setup.sh          # install everything, then start the bot
#   bash setup.sh --no-run # install everything, don't start
#
# Installs system deps (ffmpeg, python3, venv, git, build tools) using
# whatever package manager the host has (apt / dnf / yum / pacman / apk /
# brew), creates a local .venv, installs the Python requirements, and
# launches the bot. Safe to re-run — every step is idempotent.
#
set -euo pipefail

cd "$(dirname "$0")"

RUN_AFTER=1
for arg in "$@"; do
  case "$arg" in
    --no-run) RUN_AFTER=0 ;;
  esac
done

log()  { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

# --- pick a sudo prefix only if we're not already root and sudo exists ---
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi
fi

# --- 1. system dependencies (ffmpeg + python + git + build headers) ------
install_system_deps() {
  log "Installing system dependencies (ffmpeg, python3, git)…"
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y
    $SUDO apt-get install -y ffmpeg python3 python3-venv python3-pip git curl build-essential
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y ffmpeg python3 python3-pip git curl gcc || {
      warn "ffmpeg may need RPM Fusion; trying without it"
      $SUDO dnf install -y python3 python3-pip git curl gcc
    }
  elif command -v yum >/dev/null 2>&1; then
    $SUDO yum install -y epel-release || true
    $SUDO yum install -y ffmpeg python3 python3-pip git curl gcc
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -Sy --noconfirm ffmpeg python python-pip git curl base-devel
  elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache ffmpeg python3 py3-pip git curl build-base python3-dev
  elif command -v brew >/dev/null 2>&1; then
    brew install ffmpeg python git || true
  else
    warn "No known package manager found. Ensure ffmpeg + python3 are installed manually."
  fi
}

# --- 2. python venv + requirements ---------------------------------------
setup_venv() {
  PY="$(command -v python3 || command -v python)"
  [ -n "$PY" ] || die "python3 not found even after install step."
  log "Using $($PY --version 2>&1)"

  if [ ! -d .venv ]; then
    log "Creating virtualenv at .venv"
    "$PY" -m venv .venv
  fi
  # shellcheck disable=SC1091
  . .venv/bin/activate

  log "Upgrading pip and installing Python requirements…"
  python -m pip install --upgrade pip wheel setuptools
  python -m pip install -r requirements.txt
}

# --- 2b. bundled assets ---------------------------------------------------
# The default MP4/video artwork ships in the repo (bot/assets/mp4_default_art.jpg).
# Fetch it ONCE here only if it's somehow missing, so the player never has to
# download it at playback time. Non-fatal: a missing asset just falls back to
# the template-only thumbnail.
fetch_assets() {
  mkdir -p bot/assets
  # each entry: "dest_path|url"
  local assets=(
    "bot/assets/mp4_default_art.jpg|https://i.ibb.co/svmFmx4N/e734a868ca72.jpg"
    "bot/assets/vplay_image.jpg|https://i.ibb.co/zWXZfkP8/9424cd5dfc90.jpg"
  )
  local entry dest url
  for entry in "${assets[@]}"; do
    dest="${entry%%|*}"
    url="${entry#*|}"
    if [ -s "$dest" ]; then
      log "Asset present: $dest"
      continue
    fi
    log "Fetching asset → $dest"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL -o "$dest" "$url" || warn "Could not fetch $dest (a bundled fallback will be used)."
    elif command -v wget >/dev/null 2>&1; then
      wget -qO "$dest" "$url" || warn "Could not fetch $dest (a bundled fallback will be used)."
    else
      warn "Neither curl nor wget available — skipping $dest fetch."
    fi
  done
}

# --- 3. sanity checks -----------------------------------------------------
verify() {
  log "Verifying install…"
  command -v ffmpeg >/dev/null 2>&1 && log "ffmpeg: $(ffmpeg -version | head -1)" || warn "ffmpeg NOT on PATH"
  python -c "import pyrogram, pytgcalls, yt_dlp; print('[setup] python deps OK — yt-dlp', yt_dlp.version.__version__)"
}

# --- 4. .env check --------------------------------------------------------
check_env() {
  if [ ! -f .env ]; then
    if [ -f .env.example ]; then
      warn ".env not found — copying .env.example to .env. FILL IN your"
      warn "API_ID / API_HASH / BOT_TOKEN / STRING_SESSION / OWNER_ID before running."
      cp .env.example .env
    else
      warn ".env not found and no .env.example to copy. The bot will fail to start without it."
    fi
    return 1
  fi
  return 0
}

install_system_deps
setup_venv
fetch_assets
verify

if ! check_env; then
  warn "Setup finished, but .env needs your credentials. Edit .env, then run:"
  warn "  .venv/bin/python main.py"
  exit 0
fi

if [ "$RUN_AFTER" -eq 1 ]; then
  log "Starting the bot…"
  exec .venv/bin/python main.py
else
  log "Setup complete. Start the bot with:  .venv/bin/python main.py"
fi
