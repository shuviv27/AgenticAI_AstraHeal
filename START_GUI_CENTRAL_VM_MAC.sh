#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export AIQA_RUNTIME_MODE=central_vm
export AIQA_DEPLOYMENT_TOPOLOGY=central_vm_only
echo "Starting AstraHeal AI for Central VM/Mac host mode..."
python3 RUN_GUI_FIRST.py --host 0.0.0.0 --port 8080
