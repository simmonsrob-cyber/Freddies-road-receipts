# Freddie's Road Receipts (V10)

Phone photos of receipts in, cleaned scans out, filed per person, with a live "who is missing" board and an
Aircraft Commander Review that emails a small zip. Runs on a Raspberry Pi. No cloud services.

Reach it only on the home network or Tailscale. Do not use Tailscale Funnel or port forwarding for it.

## Install (on the Pi)
```
git clone https://github.com/simmonsrob-cyber/Freddies-road-receipts.git ~/frr-src
cd ~/frr-src/server && bash install.sh
```
Open `http://<pi-name>.local:8081` or `http://<tailscale-name>:8081` on a phone.
It installs its own service (`receipt-ocr`), folder (`~/receipt-app`) and port (8081). It does not touch other apps.

## Email
Edit `~/receipt-app/.env` (SMTP_USER, SMTP_PASSWORD = Gmail app password, MAIL_FROM, MAIL_TO_COMMANDER,
PUBLIC_BASE_URL), then `sudo systemctl restart receipt-ocr`. The password lives only in `.env`.

## Everyday
- Start/stop/restart: `sudo systemctl start|stop|restart receipt-ocr`
- Logs: `journalctl -u receipt-ocr -n 50`
- Update from GitHub: `bash ~/frr-src/server/update.sh` (pulls the new code, reinstalls, keeps all data)
- Everything you create lives in `~/receipt-data/` on the Pi: missions (database), original photos, scans, and the zips/PDFs. Updates never touch it. Copying that folder is a full backup.

## Tuning
`config.py`: ACCEPT_SCORE (85), TIE_MARGIN (8), ELIMINATION_ENABLED, SINGLE_NAME_PENALTY, STORE_EDGE, JPEG_QUALITY.

## People
You never have to set up a crew list. Each receipt's guest name is read and offered as a one-tap suggestion; tapping it adds that person to the mission. The People page is optional (for adding other spellings).

## Adding a person
People page, then Add person. Put other spellings seen on receipts in the second box (comma separated).
Confirming a name in "Not sure whose these are" also teaches the app that spelling.

## Tests
`pip install pytest && python -m pytest tests/` (needs tesseract installed).
