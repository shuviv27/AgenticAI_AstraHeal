#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export AIQA_RUNTIME_MODE=local_pc
export AIQA_DEPLOYMENT_TOPOLOGY=local_only
echo "Starting AstraHeal AI for Local Mac mode..."
python3 RUN_GUI_FIRST.py --host 127.0.0.1 --port 8080
