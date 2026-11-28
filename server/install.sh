#!/bin/bash
# Freddie's Road Receipts: install on this Raspberry Pi. Safe to run again.
# Run from the unzipped folder:   bash install.sh
# This does NOT touch the printer app (receipts.service, ~/receipts, port 8080),
# Tailscale, Funnel, or the Ethernet cable setup.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ME="$(id -un)"
SUDO="${SUDO-sudo}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
APP="$HOME/receipt-app"
SVC="receipt-ocr"
PORT="${PORT:-8081}"
say(){ printf '%s\n' "$*"; }
step(){ printf '\n== %s ==\n' "$*"; }
warn(){ printf '   ! %s\n' "$*"; }

step "1 of 5. Is port $PORT free?"
if ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$" && ! systemctl is-active --quiet "$SVC"; then
  warn "port $PORT is already used by something else. Run:  sudo ss -tlnp | grep :$PORT"
  warn "Pick another port and run again:  PORT=8082 bash install.sh"
  exit 1
fi
say "   Port $PORT is OK."

step "2 of 5. Programs"
$SUDO apt-get update -qq || warn "apt update did not finish. Is the Pi online?"
$SUDO apt-get install -y -qq python3-venv python3-pip tesseract-ocr tesseract-ocr-eng fonts-dejavu-core || warn "some programs did not install"

step "3 of 5. Copying the app to $APP"
mkdir -p "$APP"
if [ "$HERE" != "$APP" ]; then
  # copy code, but never overwrite the live .env or data/
  tar -C "$HERE" --exclude=.env --exclude=data --exclude=venv --exclude=__pycache__ -cf - . | tar -C "$APP" -xf -
fi
DATA="$HOME/receipt-data"
mkdir -p "$DATA"
# older installs kept data inside the app folder: move it out once, so updates can never touch it
if [ -d "$APP/data" ] && [ -n "$(ls -A "$APP/data" 2>/dev/null)" ] && [ -z "$(ls -A "$DATA" 2>/dev/null)" ]; then
  $SUDO systemctl stop "$SVC" 2>/dev/null || true
  cp -a "$APP/data/." "$DATA/" && say "   Moved your existing missions and scans to $DATA."
fi
if [ ! -f "$APP/.env" ]; then cp "$APP/.env.example" "$APP/.env"; say "   Created $APP/.env (edit it later for email)."; fi
grep -q '^DATA_DIR=' "$APP/.env" || printf '\nDATA_DIR=%s\n' "$DATA" >> "$APP/.env"
chmod 600 "$APP/.env"

step "4 of 5. Python setup (a minute or two)"
[ -x "$APP/venv/bin/python3" ] || python3 -m venv "$APP/venv" || { warn "venv failed"; exit 1; }
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt" || { warn "pip install failed. Is the Pi online?"; exit 1; }
"$APP/venv/bin/pip" install -q pillow-heif >/dev/null 2>&1 && say "   iPhone HEIC photos supported." || say "   (HEIC support not installed: set the iPhone camera to Most Compatible.)"

step "5 of 5. Starting the service"
UNIT="[Unit]
Description=Receipt OCR App
After=network-online.target
Wants=network-online.target

[Service]
User=$ME
WorkingDirectory=$APP
EnvironmentFile=$APP/.env
ExecStart=$APP/venv/bin/gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT 'app:create_app()'
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
"
printf '%s' "$UNIT" | $SUDO tee "$UNIT_DIR/$SVC.service" >/dev/null || { warn "could not write the service file"; exit 1; }
$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SVC" >/dev/null 2>&1
$SUDO systemctl restart "$SVC"
for _ in $(seq 1 15); do curl -s -m 2 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"ok"' && break; sleep 1; done
if curl -s -m 2 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"ok"'; then
  say "   Running."
  grep -q '^SMTP_USER=.\+' "$APP/.env" || say "   Email is not set up yet: edit $APP/.env, then:  sudo systemctl restart $SVC"
else
  warn "did not start. Look with:  journalctl -u $SVC -n 30"; exit 1
fi

say ""
say "  ================================================================"
say "  DONE. Open on your phone (same Wi-Fi or Tailscale):"
say "    http://$(hostname).local:$PORT"
say "    http://acars-pi2.tail5b21f4.ts.net:$PORT"
say "  Your missions, scans and PDFs live in: $DATA (updates never touch it)"
say "  Logs:    journalctl -u $SVC -n 30"
say "  Restart: sudo systemctl restart $SVC"
say "  ================================================================"
