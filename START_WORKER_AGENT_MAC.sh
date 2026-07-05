#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f worker-agent.env ]; then
  echo "worker-agent.env not found. Creating it from worker-agent.env.example."
  cp worker-agent.env.example worker-agent.env
  echo "Please edit worker-agent.env with Central VM URL and token, then rerun this script."
  exit 2
fi
echo "Starting AstraHeal AI Worker Agent..."
python3 RUN_WORKER_AGENT.py --env worker-agent.env
