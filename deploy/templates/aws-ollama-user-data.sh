#!/bin/bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y curl

curl -fsSL https://ollama.com/install.sh | sh
systemctl enable ollama
systemctl start ollama
