#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/opt/secretary-bot"
APP_DIR="$BASE_DIR/app"
VENV_DIR="$BASE_DIR/venv"
RUNTIME_DIR="$BASE_DIR/runtime"
SOURCE_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
UNIT_SOURCE="$SOURCE_DIR/deploy/systemd/secretary-bot.service"
UNIT_TARGET="/etc/systemd/system/secretary-bot.service"

export DEBIAN_FRONTEND=noninteractive

mkdir -p "$APP_DIR" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/chat_archive"

apt-get update
apt-get install -y python3 python3-venv python3-pip git curl ca-certificates nodejs npm tar

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

if ! command -v codex >/dev/null 2>&1; then
    npm install -g @openai/codex
fi

install -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl daemon-reload
systemctl enable secretary-bot.service

if [ ! -f "$RUNTIME_DIR/config.yaml" ] && [ -f "$SOURCE_DIR/config.example.yaml" ]; then
    cp "$SOURCE_DIR/config.example.yaml" "$RUNTIME_DIR/config.yaml"
    chmod 600 "$RUNTIME_DIR/config.yaml"
    echo "Created runtime/config.yaml from config.example.yaml"
else
    echo "Kept existing runtime/config.yaml"
fi

if [ ! -f "$RUNTIME_DIR/context.md" ] && [ -f "$SOURCE_DIR/context.example.md" ]; then
    cp "$SOURCE_DIR/context.example.md" "$RUNTIME_DIR/context.md"
    echo "Created runtime/context.md from context.example.md"
else
    echo "Kept existing runtime/context.md"
fi

echo "Bootstrap completed for $BASE_DIR"
