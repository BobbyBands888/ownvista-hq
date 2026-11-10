#!/bin/bash
# One-time setup of the Ten-Four Tapes publisher on Bobby's Mac. Free — nothing here costs money.
# Run:  bash ~/Downloads/ownvista-hq/mac/install.sh
# Safe to run again any time (updates the code, keeps your keys and videos).
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
TFT="$HOME/TenFourTapes"
REPO="$TFT/hq"
say() { printf "\n\033[1m%s\033[0m\n" "$1"; }

say "1/6  Folders + code  →  $REPO"
mkdir -p "$TFT"/{footage,queue,rendered,models,fonts,logs} "$HOME/Library/LaunchAgents"
if [ "$SRC" != "$REPO" ]; then
  mkdir -p "$REPO"
  [ -f "$REPO/.env" ] && cp "$REPO/.env" "$TFT/.env.keep"
  rsync -a --delete --exclude ".env" "$SRC/" "$REPO/"
  [ -f "$TFT/.env.keep" ] && mv "$TFT/.env.keep" "$REPO/.env"
fi

say "2/6  Python 3.12 + video tools (uv, free)"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
[ -x "$TFT/venv/bin/python" ] || "$UV" venv --python 3.12 "$TFT/venv"
PY="$TFT/venv/bin/python"
"$UV" pip install --python "$PY" -q -r "$REPO/mac/requirements-mac.txt"

say "3/6  Narrator voice (Kokoro, ~350 MB, one time)"
KO="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
[ -s "$TFT/models/kokoro-v1.0.onnx" ] || curl -L --fail -o "$TFT/models/kokoro-v1.0.onnx" "$KO/kokoro-v1.0.onnx"
[ -s "$TFT/models/voices-v1.0.bin" ] || curl -L --fail -o "$TFT/models/voices-v1.0.bin" "$KO/voices-v1.0.bin"

say "4/6  Fonts (Inter)"
if [ ! -s "$TFT/fonts/Inter-Black.ttf" ]; then
  curl -L --fail -o "$TFT/fonts/inter.zip" https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip
  unzip -j -o -q "$TFT/fonts/inter.zip" "extras/ttf/Inter-Black.ttf" "extras/ttf/Inter-Bold.ttf" -d "$TFT/fonts"
  rm -f "$TFT/fonts/inter.zip"
fi

say "5/6  Keys"
if [ -f "$REPO/.env" ] && "$PY" "$REPO/mac/setup_env.py" --check; then
  echo "Keys already set and working."
else
  "$PY" "$REPO/mac/setup_env.py"
fi

say "6/6  Schedule (every 30 min while the Mac is awake)"
PL="$HOME/Library/LaunchAgents/com.tenfourtapes.runner.plist"
sed -e "s#__REPO__#$REPO#g" -e "s#__PY__#$PY#g" -e "s#__HOME__#$HOME#g" "$REPO/mac/com.tenfourtapes.runner.plist" > "$PL"
launchctl unload "$PL" 2>/dev/null || true
launchctl load "$PL"

say "Done. The publisher is running."
echo "  New videos land in:  $TFT/rendered   (you'll get a Mac notification to review each one)"
echo "  Approve them on:     https://levelingclips.com"
echo "  Log:                 $TFT/logs/runner.log"
