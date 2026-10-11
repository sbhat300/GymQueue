#!/usr/bin/env bash
# Installs Presage's SmartSpectra C++ SDK from their apt repo (Ubuntu 24.04 / noble) if it isn't
# already there, then builds presage/build/presage_vitals - the binary gymvision/vitals.py calls.
set -euo pipefail
cd "$(dirname "$0")"

if ! pkg-config --exists SmartSpectra 2>/dev/null; then
    echo "SmartSpectra SDK not found - installing libsmartspectra-dev (needs sudo)"
    sudo apt-get install -y cmake curl gpg pkg-config
    sudo install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://packages.presagetech.com/KEY.gpg \
        | sudo gpg --dearmor --yes -o /etc/apt/keyrings/presage-archive-keyring.gpg
    sudo chmod 644 /etc/apt/keyrings/presage-archive-keyring.gpg
    echo "deb [signed-by=/etc/apt/keyrings/presage-archive-keyring.gpg] https://packages.presagetech.com/apt/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
        | sudo tee /etc/apt/sources.list.d/presage-technologies.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y libsmartspectra-dev
fi
echo "SmartSpectra SDK $(pkg-config --modversion SmartSpectra)"

cmake -S . -B build
cmake --build build -j
echo "built $(pwd)/build/presage_vitals"
