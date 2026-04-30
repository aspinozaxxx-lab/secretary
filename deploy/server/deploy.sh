#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/opt/secretary-bot"
APP_DIR="$BASE_DIR/app"
VENV_DIR="$BASE_DIR/venv"
RUNTIME_DIR="$BASE_DIR/runtime"
SOURCE_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
UNIT_SOURCE="$SOURCE_DIR/deploy/systemd/secretary-bot.service"
UNIT_TARGET="/etc/systemd/system/secretary-bot.service"

mkdir -p "$APP_DIR" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/chat_archive"

TMP_APP="$(mktemp -d)"
cleanup() {
    rm -rf "$TMP_APP"
}
trap cleanup EXIT

tar \
    --exclude='./.git' \
    --exclude='./config.yaml' \
    --exclude='./context.md' \
    --exclude='./context.backups' \
    --exclude='./state.json' \
    --exclude='./logs' \
    --exclude='./chat_archive' \
    --exclude='./build' \
    --exclude='./dist' \
    --exclude='./__pycache__' \
    -C "$SOURCE_DIR" -cf - . | tar -C "$TMP_APP" -xf -

find "$APP_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
tar -C "$TMP_APP" -cf - . | tar -C "$APP_DIR" -xf -
chown -R root:root "$APP_DIR"

if [ ! -f "$VENV_DIR/pyvenv.cfg" ] || ! grep -q "include-system-site-packages = true" "$VENV_DIR/pyvenv.cfg"; then
    rm -rf "$VENV_DIR"
    python3 -m venv --system-site-packages "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel || true
if ! "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"; then
    echo "WARNING: pip install failed, checking apt-provided Python packages"
    "$VENV_DIR/bin/python" -c "import requests, yaml; print('apt-provided Python dependencies ok')"
fi

install -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl daemon-reload

if [ ! -f "$RUNTIME_DIR/config.yaml" ] && [ -f "$APP_DIR/config.example.yaml" ]; then
    cp "$APP_DIR/config.example.yaml" "$RUNTIME_DIR/config.yaml"
    chmod 600 "$RUNTIME_DIR/config.yaml"
    echo "Created runtime/config.yaml from config.example.yaml"
else
    echo "Kept existing runtime/config.yaml"
fi

if [ ! -f "$RUNTIME_DIR/context.md" ] && [ -f "$APP_DIR/context.example.md" ]; then
    cp "$APP_DIR/context.example.md" "$RUNTIME_DIR/context.md"
    echo "Created runtime/context.md from context.example.md"
else
    echo "Kept existing runtime/context.md"
fi

echo "Runtime state.json, logs and chat_archive were not copied or removed"

systemctl restart secretary-bot.service
sleep 3
systemctl status secretary-bot.service --no-pager || true
journalctl -u secretary-bot.service -n 100 --no-pager || true
systemctl is-active --quiet secretary-bot.service
