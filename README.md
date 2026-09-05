# Ledger402

Autonomous intelligence procurement on XRPL Testnet. The user states a **business objective**; a
LangGraph agent classifies it, discovers providers, ranks them on **confidence bought per drop**,
settles over x402 on the XRP Ledger, **re-measures its own uncertainty against the evidence that
arrived**, and buys again or stops. Payment is part of the workflow, not the product.

**The LLM never decides to spend money.** Inference is confined to understanding the question and
writing the report; every economic decision is deterministic and unit-tested. With no
`GROQ_API_KEY` set, the agent runs fully deterministically. See [AGENT_PLAN.md](AGENT_PLAN.md).

**Real:** x402, XRPL Testnet settlement, the LangGraph loop, budget and policy rails, the audit
anchor, HTTP provider architecture. Verified end to end on the XRPL Testnet — a full two-settlement
run produced `tesSUCCESS` payments of 1200 and 600 drops, validated in ledgers 20493969 and 20493983.

**Testnet XRP is not money.** It comes free from a faucet, has no value, cannot be exchanged, and
lives on a ledger separate from Mainnet. There is nothing to buy and nothing to lose. The build
refuses to sign against anything but a recognised test network — see
[ledger402/network.py](ledger402/network.py); `GET /capabilities` reports the current posture.

**Synthetic:** port data, satellite data, telemetry, provider identities, ODRL terms, commercial
pricing. The confidence model is a calibrated heuristic, not a validated forecasting model.

Supported task type: `port_congestion` (Port X). Anything else fails closed with 400 rather than
being answered with Port X evidence.

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

Leave every other value from `.env.example` unchanged. Each person funds their own wallets. Never commit `.env`, never share the buyer seed, never reuse another teammate's seed.

Then start all four processes (Ctrl+C stops them together):

```bash
make dev-start
```

| What | URL |
| --- | --- |
| Business dashboard (Streamlit) | http://localhost:8501 |
| **Agent execution animation** | **http://localhost:8000/live** |
| Orchestrator | http://localhost:8000 |
| Free provider | http://localhost:8001 |
| Premium provider (satellite, 1200 drops) | http://localhost:8002 |
| Telemetry provider (terminal ops, 600 drops) | http://localhost:8003 |

Ports `8000`, `8001`, `8002`, `8003`, and `8501` must be free.

### Demo: the two screens

The deliverable spec asks for a dual-screen demo. Both screens are served by `make dev-start`:

- **Screen 1 — http://localhost:8501** the business dashboard: verdict, confidence waterfall, signals, ODRL rights.
- **Screen 2 — http://localhost:8000/live** the agent execution animation: the decision graph with the
  current node lit, confidence and budget gauges moving, the provider ranking as the agent computes it,
  and each XRPL settlement as it lands. Gold means real money moving.

The animation is driven by server-sent events from the agent itself (`GET /research/stream`), one message
per audit entry — it is a view over the real run, not a scripted replay. Events are paced for legibility
and speed up if they queue, so it never drifts behind the agent. Run the agent **from the animation page**
(it has its own controls) and watch both screens.

### Demo in the UI

1. Open http://localhost:8501
2. Leave the default objective: `Assess whether Port X is becoming congested.`
3. Leave budget at **5000** drops and target confidence at **0.85**
4. Click **Run research** (can take a few minutes; it settles on Testnet)

**Executive briefing** shows the verdict, the confidence waterfall (what each purchase was worth),
and the congestion signals. **Agent execution** shows the per-iteration ranking — including what the
agent *declined* to buy and why — and the timestamped log. **Evidence & rights** shows each payload
with the ODRL usage rights that arrived with payment.

Then raise the target to **0.92** and run again: the same agent settles a second time against the
cheaper telemetry feed, and stops at 91.6% rather than claiming it hit the target.

Unsupported objectives (anything that is not port congestion) return **400** and never receive Port X
evidence.

### Optional: LLM reasoning

Groq is the hackathon's provided inference stack. Add a key to `.env` to enable LLM question
classification and report writing:

```dotenv
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

Everything still runs without it. `GET /capabilities` reports which path is active. The LLM cannot
widen the set of task types the agent serves, and cannot authorise a purchase.

### Tests vs live payment

```bash
make test      # mocked; never spends Testnet XRP
make pay-once  # one real 1200-drop Testnet payment (needs .env + running premium provider, or run after make dev-start)
```

Purchase idempotency is **process-local** (`run_id + provider_id` in memory: NOT_STARTED / PENDING / SUCCESS / FAILED / UNKNOWN). Restarting the orchestrator clears it. No database. `UNKNOWN` means the client failed after a transaction may already have been submitted; the same run will not pay again.

### If something fails

| Symptom | What to do |
| --- | --- |
| `Python 3.11+ is required` | Use a 3.11+ `python3` (see Prerequisites) |
| `XRPL wallet configuration missing` | `.env` is missing, or `XRPL_WALLET_SEED` / `XRPL_PAY_TO` are empty. Re-run `make wallet-setup` and paste the two lines |
| Faucet / wallet-setup error | Testnet faucet flakes. Wait a minute and run `make wallet-setup` again |
| Port already in use | Stop the old `make dev-start` (Ctrl+C) or kill whatever is on 8000–8003 / 8501 |
| UI error / 402 after a restart | Confirm `make dev-start` is still running and `.env` still has the seed |

### Remaining work

The agentic loop, ranking, audit anchor, ODRL and dashboard are in. What is still open:

- **More than one task type.** `port_congestion` is the only spec in [ledger402/tasks.py](ledger402/tasks.py). Adding private credit or supply-chain tasks is now a matter of declaring signals and providers, not changing the graph.
- **Persistence.** Purchase idempotency is process-local and dies on orchestrator restart. A run store is needed before the loop can survive a crash mid-purchase.
- **Reconciliation for `UNKNOWN` payments.** The agent correctly refuses to retry, but nothing later checks whether that transaction actually settled.
- **Confidence model validation.** `FLOOR`/`SPAN` in [ledger402/confidence.py](ledger402/confidence.py) are calibrated to the demo, not fitted to data.
- **RLUSD.** Cleaner commercial amounts than micro-XRP drops; drops stay the on-chain unit until then.
- **Not next unless the demo needs it:** live provider APIs, Docker/cloud, x402-secure VI, accounts/auth.
