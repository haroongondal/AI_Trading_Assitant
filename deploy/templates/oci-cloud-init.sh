#!/bin/bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y curl ufw

curl -fsSL https://ollama.com/install.sh | sh
systemctl enable ollama
systemctl start ollama

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
