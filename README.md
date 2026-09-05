# Ledger402

Two-sided agent-native data clearinghouse on XRPL Testnet. A buyer agent states a **business
objective**; a LangGraph loop classifies it, discovers B2B and B2C providers, ranks them on
**confidence bought per drop**, settles over x402, **re-measures its own uncertainty**, and
delivers either a Tier 1 advisory dossier or a Tier 2 verified data bundle.

**The LLM never decides to spend money.** Gemini is confined to understanding the question and
(Tier 1 only) writing prose. Ranking, confidence (`FLOOR=0.56`, `SPAN=0.511`), policy, and
settlement stay deterministic Python. With no `GEMINI_API_KEY`, the agent runs fully
deterministically. See [AGENT_PLAN.md](AGENT_PLAN.md).

**Real:** x402, XRPL Testnet settlement, the LangGraph loop, budget and policy rails, the audit
anchor, HTTP provider architecture. Verified end to end on the XRPL Testnet — a full two-settlement
run produced `tesSUCCESS` payments of 1200 and 600 drops, validated in ledgers 20493969 and 20493983.

**Testnet XRP is not money.** It comes free from a faucet, has no value, cannot be exchanged, and
lives on a ledger separate from Mainnet. The build refuses to sign against anything but a recognised
test network — see [ledger402/network.py](ledger402/network.py); `GET /capabilities` reports the
current posture.

**Synthetic:** port data, satellite data, telemetry, curator CSV, provider identities, ODRL terms,
commercial pricing. The confidence model is a calibrated heuristic, not a validated forecasting model.

Supported task type: `port_congestion` (Port of Singapore / PSA / SGSIN). Anything else fails closed
with 400 rather than being answered with SGSIN evidence.

### What the agent does with the budget

The default 5000-drop budget is data procurement only; XRPL network fees are reported separately
and never deducted from it.

| Target confidence | Settlements | Spent | Reached |
| --- | --- | --- | --- |
| 0.85 (default) | 1 — satellite feed | 1200 drops / 0.0012 XRP | 87% |
| 0.92 | 2 — satellite, then telemetry | 1800 drops / 0.0018 XRP | 91.6%, then stops |

Same agent, same code. The spend is a consequence of the objective, not a script.

## Local setup

### Clone

```bash
git clone https://github.com/LAIN-21/ripple-challenge.git
cd ripple-challenge
git checkout -b your-feature
```

Work on a new branch. Open a pull request for every change.

### Prerequisites

- **Python 3.11+** (`python3 --version`). `x402-xrpl` will not install on 3.10 or older. On macOS, `python3` is often still 3.9 — install 3.11+ from python.org or `brew install python@3.12`.
- `make`
- Internet (Testnet faucet + x402 facilitator)
- **Node 18+** only if you use Cursor/Claude in this repo (feedback hook)

Do not activate the venv yourself. Make uses `.venv/bin/python` and `.venv/bin/pip`.

### Feedback hook (once per person)

The Cursor hook is already registered in `.cursor/hooks.json`. Each teammate still needs their **own** identity file. Do not copy someone else's `~/.xrpl-feedback-hook.json`.

```bash
TEAM_NAME="CYBERLEEK" HACKER_NAME="Your Real Name" node hook/setup.mjs --non-interactive
cat ~/.xrpl-feedback-hook.json
```

Full details: [hook/INSTALL.md](hook/INSTALL.md).

### First run

```bash
make install
cp .env.example .env
make wallet-setup
```

`make wallet-setup` funds two XRPL Testnet wallets (buyer + merchant) and **prints** credentials. It does **not** write `.env`. Paste these two lines into `.env`:

```dotenv
XRPL_WALLET_SEED=<buyer seed from the printout>
XRPL_PAY_TO=<merchant address from the printout>
```

Optionally add `GEMINI_API_KEY` for classification and Tier 1 prose. Leave every other value from `.env.example` unchanged. Each person funds their own wallets. Never commit `.env`, never share the buyer seed, never reuse another teammate's seed.

Then start the three processes (Ctrl+C stops them together):

```bash
make dev-start
```

| What | URL |
| --- | --- |
| Business dashboard (Streamlit) | http://localhost:8501 |
| **Agent execution animation** | **http://localhost:8000/live** |
| Orchestrator / SSE | http://localhost:8000 |
| Provider gateway (`server.py`, B2B + B2C) | http://localhost:8001 |

Ports `8000`, `8001`, and `8501` must be free.

Canonical B2B routes on the gateway:

- `GET /api/b2b/public-stats` — 200, 0 drops
- `GET /api/b2b/satellite-logistics` — unpaid 402, 1200 drops
- `GET /api/b2b/terminal-telemetry` — unpaid 402, 600 drops
- `POST /api/b2c/upload` — curator CSV/JSON, default 400 drops (not auto-registered)

### Demo: the two screens

The deliverable spec asks for a dual-screen demo. Both screens are served by `make dev-start`:

- **Screen 1 — http://localhost:8501** three-panel dashboard: inputs and delivery tier on the left, dossier or data bundle in the centre, live execution + B2C upload on the right.
- **Screen 2 — http://localhost:8000/live** the agent execution animation: the decision graph with the current node lit, confidence and budget gauges moving, the provider ranking as the agent computes it, and each XRPL settlement as it lands.

The animation is driven by server-sent events from the agent itself (`GET /research/stream`). Check **Use Offline Replay Mode** in Streamlit to walk the 58% → 87% → 91.6% path on recorded Testnet hashes without signing.

### Demo in the UI

1. Open http://localhost:8501
2. Leave the default objective: `Assess whether Port of Singapore (PSA) is facing critical yard and terminal congestion`
3. Leave budget at **5000** drops and target confidence at **0.85**
4. Choose **Tier 1: Strategic Advisory Dossier** (or Tier 2 for the raw bundle)
5. Click **Run research** (live settlement can take a few minutes)

Then raise the target to **0.92** and run again: the same agent settles a second time against the cheaper telemetry feed, and stops at 91.6% rather than claiming it hit the target.

Unsupported objectives (anything that is not port congestion) return **400** and never receive SGSIN evidence. A question about a different port (for example Port Klang) against held SGSIN payloads returns `UNCLEAR / INSUFFICIENT_EVIDENCE`.

The centre pane offers `st.download_button` exports: `Ledger402_Advisory_Dossier.md` (Tier 1) or `Ledger402_Data_Bundle.json` / `Ledger402_Data_Bundle.csv` (Tier 2). The 75% Tier 2 discount is product SKU copy only — x402 prices stay 1200 + 600.

### Optional: LLM reasoning

Gemini writes classification and Tier 1 prose. Add a key to `.env`:

```dotenv
GEMINI_API_KEY=...
```

Cascade (one attempt each): `gemini-2.5-flash` → `gemini-2.5-pro` → `gemini-1.5-flash`. Everything still runs without a key. `GET /capabilities` reports which path is active. The LLM cannot widen the set of task types the agent serves, and cannot authorise a purchase.

### Tests vs live payment

```bash
make test          # mocked; never spends Testnet XRP; no Gemini calls
make pay-once      # one real 1200-drop Testnet payment against /api/b2b/satellite-logistics
```

Purchase idempotency is **process-local** (`run_id + provider_id` in memory: NOT_STARTED / PENDING / SUCCESS / FAILED / UNKNOWN). Restarting the orchestrator clears it. No database. `UNKNOWN` means the client failed after a transaction may already have been submitted; the same run will not pay again.

Replay mode uses the recorded hashes in [`providers_data.py`](providers_data.py) (`OFFLINE_REPLAY_SETTLEMENTS`) and never calls `purchase_premium`.

### If something fails

| Symptom | What to do |
| --- | --- |
| `Python 3.11+ is required` | Use a 3.11+ `python3` (see Prerequisites) |
| `XRPL wallet configuration missing` | `.env` is missing, or `XRPL_WALLET_SEED` / `XRPL_PAY_TO` are empty. Re-run `make wallet-setup` and paste the two lines |
| Faucet / wallet-setup error | Testnet faucet flakes. Wait a minute and run `make wallet-setup` again |
| Port already in use | Stop the old `make dev-start` (Ctrl+C) or kill whatever is on 8000 / 8001 / 8501 |
| UI error / 402 after a restart | Confirm `make dev-start` is still running and `.env` still has the seed |

### Remaining work

The agentic loop, two-sided marketplace, ranking, audit anchor, ODRL and dashboard are in. What is still open:

- **More than one task type.** `port_congestion` is the only spec in [ledger402/tasks.py](ledger402/tasks.py). Adding private credit or supply-chain tasks is now a matter of declaring signals and providers, not changing the graph.
- **Persistence.** Purchase idempotency is process-local and dies on orchestrator restart. A run store is needed before the loop can survive a crash mid-purchase.
- **Reconciliation for `UNKNOWN` payments.** The agent correctly refuses to retry, but nothing later checks whether that transaction actually settled.
- **Confidence model validation.** `FLOOR`/`SPAN` in [ledger402/confidence.py](ledger402/confidence.py) are calibrated to the demo, not fitted to data.
- **RLUSD.** Cleaner commercial amounts than micro-XRP drops; drops stay the on-chain unit until then.
- **Not next unless the demo needs it:** live provider APIs, Docker/cloud, x402-secure VI, accounts/auth.
