#!/bin/bash
# Update: pull the newest code from GitHub, then run the installer again.
# Your missions, scans, PDFs (in ~/receipt-data) and your .env are never touched.
set -e
cd "$(dirname "$0")"
git pull --ff-only
bash install.sh
