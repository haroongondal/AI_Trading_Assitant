#!/bin/bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip build-essential nginx certbot python3-certbot-nginx

mkdir -p /opt/ai-trading-assistant
chown ubuntu:ubuntu /opt/ai-trading-assistant
