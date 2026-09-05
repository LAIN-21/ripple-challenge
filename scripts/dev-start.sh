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
export PROVIDER_URL="${PROVIDER_URL:-http://localhost:8001}"
export FREE_PROVIDER_URL="${FREE_PROVIDER_URL:-$PROVIDER_URL}"
export PREMIUM_PROVIDER_URL="${PREMIUM_PROVIDER_URL:-$PROVIDER_URL}"
export TELEMETRY_PROVIDER_URL="${TELEMETRY_PROVIDER_URL:-$PROVIDER_URL}"
export B2C_PROVIDER_URL="${B2C_PROVIDER_URL:-$PROVIDER_URL}"
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
"$PY" -m uvicorn server:app --host 127.0.0.1 --port 8001 &
pids+=($!)
"$PY" -m uvicorn apps.chat.main:app --host 127.0.0.1 --port 8600 &
pids+=($!)
"$ST" run apps/ui/app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false &
pids+=($!)

echo
echo "Ledger402 running"
echo
echo "Chat (user screen):"
echo "http://localhost:8600"
echo
echo "Clearinghouse (switch screen):"
echo "http://localhost:8501"
echo
echo "Agent execution animation (unused for the chat demo):"
echo "http://localhost:8000/live"
echo
echo "Orchestrator:"
echo "http://localhost:8000"
echo
echo "Provider gateway (B2B + B2C):"
echo "http://localhost:8001"
echo

sleep 2
for url in http://127.0.0.1:8000/health http://127.0.0.1:8001/health http://127.0.0.1:8600/health; do
  if ! curl -sf "$url" >/dev/null; then
    echo "Warning: $url is not reachable yet."
  fi
done

wait
