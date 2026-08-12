#!/usr/bin/env bash
# Warborn Music — one-shot VPS installer.
# Usage (from a clean Debian/Ubuntu VPS, running as root or with sudo):
#   git clone https://github.com/YOUR_USERNAME/warborn-music
#   cd warborn-music
#   sudo bash scripts/install.sh
#
# Re-run any time you pull new code — it's idempotent.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="warborn-music"
SERVICE_USER="${SUDO_USER:-$(whoami)}"
PYTHON_BIN="$(command -v python3 || true)"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
red() { printf "\033[31m%s\033[0m\n" "$*" >&2; }

if [[ $EUID -ne 0 ]]; then
  red "Run with sudo: sudo bash scripts/install.sh"
  exit 1
fi

green "==> Installing system packages"
apt-get update -y
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-dev \
  build-essential git ffmpeg curl ca-certificates

if [[ ! -d "$REPO_DIR/.venv" ]]; then
  green "==> Creating virtualenv at $REPO_DIR/.venv"
  python3 -m venv "$REPO_DIR/.venv"
fi

green "==> Installing Python dependencies"
"$REPO_DIR/.venv/bin/pip" install --upgrade pip
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

if [[ ! -f "$REPO_DIR/.env" ]]; then
  yellow "==> No .env found — writing a template at $REPO_DIR/.env"
  cat > "$REPO_DIR/.env" <<'EOF'
API_ID=
API_HASH=
BOT_TOKEN=
STRING_SESSION=
# Optional — only needed if users will paste Spotify track links.
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
# Optional — yt-dlp cookies path (Netscape format) for YouTube login.
COOKIES_FILE=
EOF
  chown "$SERVICE_USER":"$SERVICE_USER" "$REPO_DIR/.env"
  chmod 600 "$REPO_DIR/.env"
  yellow "    Fill in API_ID, API_HASH, BOT_TOKEN, STRING_SESSION before starting."
fi

green "==> Writing systemd unit /etc/systemd/system/${SERVICE_NAME}.service"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Warborn Music
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${REPO_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${REPO_DIR}/.venv/bin/python ${REPO_DIR}/main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

green "==> Reloading systemd and enabling service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

if grep -qE '^(API_ID|BOT_TOKEN|STRING_SESSION)=[^[:space:]]+' "$REPO_DIR/.env"; then
  green "==> Restarting service"
  systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
else
  yellow "==> .env is incomplete — not starting yet."
  yellow "    Edit $REPO_DIR/.env, then run: sudo systemctl restart ${SERVICE_NAME}"
fi

cat <<EOF

$(green "Done.")

Useful commands:
  sudo systemctl restart ${SERVICE_NAME}     # restart after editing .env or pulling new code
  sudo systemctl status  ${SERVICE_NAME}     # check current state
  sudo journalctl -u ${SERVICE_NAME} -f      # tail live logs
  sudo systemctl stop    ${SERVICE_NAME}     # stop the bot
  sudo systemctl disable ${SERVICE_NAME}     # don't start on boot

To update later:
  cd ${REPO_DIR}
  git pull
  sudo bash scripts/install.sh
EOF
