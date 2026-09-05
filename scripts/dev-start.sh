#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WALLET_MSG='XRPL wallet configuration missing.
Run `make wallet-setup`, copy the printed values into `.env`,
then run `make dev-start` again.'

if [[ ! -f .env ]]; then
  echo "$WALLET_MSG"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${XRPL_WALLET_SEED:-}" || -z "${XRPL_PAY_TO:-}" ]]; then
  echo "$WALLET_MSG"
  exit 1
fi

export PYTHONPATH="$ROOT"
PY="$ROOT/.venv/bin/python"
ST="$ROOT/.venv/bin/streamlit"

pids=()

cleanup() {
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}

trap cleanup INT TERM EXIT

"$PY" -m uvicorn apps.orchestrator.main:app --host 127.0.0.1 --port 8000 &
pids+=($!)
"$PY" -m uvicorn apps.free_provider.main:app --host 127.0.0.1 --port 8001 &
pids+=($!)
"$PY" -m uvicorn apps.premium_provider.main:app --host 127.0.0.1 --port 8002 &
pids+=($!)
"$PY" -m uvicorn apps.telemetry_provider.main:app --host 127.0.0.1 --port 8003 &
pids+=($!)
"$ST" run apps/ui/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false &
pids+=($!)

echo
echo "Ledger402 running"
echo
echo "Business dashboard:"
echo "http://localhost:8501"
echo
echo "Agent execution animation (open this on the second screen):"
echo "http://localhost:8000/live"
echo
echo "Orchestrator:"
echo "http://localhost:8000"
echo
echo "Free Provider:"
echo "http://localhost:8001"
echo
echo "Premium Provider (satellite, 1200 drops):"
echo "http://localhost:8002"
echo
echo "Telemetry Provider (terminal ops, 600 drops):"
echo "http://localhost:8003"
echo

sleep 2
for url in http://127.0.0.1:8000/health http://127.0.0.1:8001/health http://127.0.0.1:8002/health http://127.0.0.1:8003/health; do
  if ! curl -sf "$url" >/dev/null; then
    echo "Warning: $url is not reachable yet."
  fi
done

wait
