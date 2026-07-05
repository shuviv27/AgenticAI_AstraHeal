#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export AIQA_RUNTIME_MODE=vm_with_workers
export AIQA_DEPLOYMENT_TOPOLOGY=central_vm_plus_worker_agents
export AIQA_ENABLE_WORKER_AGENTS=true
echo "Starting AstraHeal AI Central VM + Worker Agents mode..."
python3 RUN_GUI_FIRST.py --host 0.0.0.0 --port 8080
