#!/bin/bash
set -e

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y isc-dhcp-client iproute2

echo "Running tests..."
sudo pytest -n auto tests/
