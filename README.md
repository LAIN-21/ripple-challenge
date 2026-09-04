# Ledger402

Autonomous intelligence procurement on XRPL Testnet. The user asks a **business question**; a deterministic workflow decides whether buying premium evidence is worth the cost. Payment is part of the workflow, not the product. Morning MVP supports **one** task type: `port_congestion` (Port X congestion). It is not a general research agent and does not use LangChain/LangGraph.

**Real:** x402, XRPL Testnet settlement, deterministic procurement loop, budget policy, HTTP provider architecture.

**Synthetic:** port data, satellite data, provider identities, commercial pricing. This is **not** a live satellite or vendor integration.

Demo amounts (integer drops internally; XRP for display only). The budget is **data procurement only** and does **not** include the XRPL network fee:

- Data procurement budget: **5000 drops / 0.005 XRP**
- Premium query: **1200 drops / 0.0012 XRP**
- Procurement remaining: **3800 drops / 0.0038 XRP**

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
| Streamlit UI | http://localhost:8501 |
| Orchestrator | http://localhost:8000 |
| Free provider | http://localhost:8001 |
| Premium provider | http://localhost:8002 |

Ports `8000`, `8001`, `8002`, and `8501` must be free.

### Demo in the UI

1. Open http://localhost:8501
2. Leave the default question: `Assess whether Port X is becoming congested.`
3. Leave budget at **5000** drops
4. Click **Run Research** (can take up to ~3 minutes; it pays Testnet)

You should see BUY → HTTP 402 → XRPL payment of 1200 drops → premium unlock, confidence **58% → 87%**, remaining budget **3800 drops**, and a Testnet explorer link in the sidebar.

Unsupported questions (anything that is not port congestion) return **400**. They will not receive Port X congestion answers.

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
| Port already in use | Stop the old `make dev-start` (Ctrl+C) or kill whatever is on 8000–8002 / 8501 |
| UI error / 402 after a restart | Confirm `make dev-start` is still running and `.env` still has the seed |

### Remaining work

The morning MVP is a **deterministic procurement loop**, not an agent. Payment, policy, and the Port X demo work; the next job is to make the agent real without breaking the commercial loop.

- **Agentic architecture.** Replace the hardcoded `port_congestion` state machine with an agent that classifies the question, discovers providers, decides whether to buy, reassesses after unlock, and can buy again, branch, retry, or stop. LangGraph (or equivalent) is justified here; do not keep pretending the current workflow is an agent.
- **More than one task type.** Unsupported questions should be understood and routed, not only rejected with 400.
- **Multiple premium providers.** Rank options on price vs expected information gain; do not always buy the same satellite feed.
- **LLM-written research output.** Templated 58% → 87% copy is a placeholder for a real answer grounded in purchased evidence.
- **RLUSD (optional later).** Cleaner commercial amounts than micro-XRP drops; keep drops as the on-chain unit until then.
- **Persistence.** Process-local idempotency dies on orchestrator restart; a real run store is needed before multi-step agent loops.
- **Not next unless we need it for demo:** live satellite APIs, Docker/cloud, ODRL, x402-secure VI, accounts/auth.

Morning build plan (what shipped): [PLAN.md](PLAN.md). Challenge brief continues below.

---

# Ripple — AI-Native Business on XRPL

## 🚨 SETUP A FEEDBACK HOOK!! 🚨

Copy and paste below instruction to your LLM client (Claude Code, Codex, etc):

```
Download feedback hook installation instructions from https://github.com/Singhacks-2026/ripple/blob/main/agent-instruction.md and install the hook accordingly.
```

This is crucial in securing feedback scores for the hackathon. Failure to set up the feedback hook properly may result in lower total score for the hackathon.

---

## Load the XRPL agentic-resources skill (recommended)

This repo ships an agent skill that loads a curated set of XRPL AI and agent resources into your coding agent: agent wallets, x402 pay-per-call, agent credit, RLUSD, live amendment and fee status, and the XLS specs. It works in Claude Code, Cursor, and Codex.

From the repo root:

```
bash skills/install.sh
```

Then invoke it in your agent by typing `/xrpl-agentic-resources`, or just start XRPL agent work and the agent loads it by description. On first use, run `bash skills/xrpl-agentic-resources/scripts/refresh.sh` to pull the vendored repos and fresh docs indexes. See [skills/README.md](./skills/README.md) for per-agent details.

---

> **Build an AI-Native Business on XRPL with the XRPL AI Starter Kit and x402** — Design a credible product or service that could only exist, or operate significantly better, because AI agents can discover, decide, transact, and deliver value autonomously.

## Challenge Summary

**Goal**: Design an AI-native product or service that solves a real customer problem and demonstrates how autonomous agentic payments can enable a new or significantly better business experience.

**Build path**: Create a working AI-agent-powered prototype using the **XRP Ledger**, **XRPL AI Starter Kit**, **x402**, **MPP**, and all other resources specified in [resources.md](./resources.md) to demonstrate a complete commercial loop from customer need → payment → value delivered.

> **📖 IMPORTANT**: Before starting your build, please read this **README.md** and [resources.md](./resources.md) first. It contains the challenge context, requirements, and guidance to help you build a strong solution.

---

## 📋 The Problem We're Solving

### Current State

* AI agents are increasingly able to discover services, compare options, make decisions, complete work, and interact with digital systems
* Most digital commerce still requires humans to manually initiate, approve, or complete transactions
* Existing AI applications often stop at recommendations or actions rather than participating directly in economic activity
* Machine-to-machine payments create the potential for agents to independently purchase APIs, data, compute, digital services, and other resources
* The opportunity is not simply to make an AI agent send a blockchain transaction

There is an opportunity to create **AI-native businesses where autonomous payments are a core part of how the product works and creates value**.

### What You're Building

A working AI-agent-powered product or service that identifies a real customer need and demonstrates a **complete commercial loop**.

The solution should demonstrate:

* A clear customer problem
* A meaningful role for an AI agent
* Agent discovery or decision-making
* Autonomous agentic payments (x402, MPP, or other agentic payment standards are recommended)
* XRPL settlement or transaction activity
* Delivery of a useful product, service, or outcome
* A credible business or commercial model

### Who Benefits

* **Primary users**: Customers or businesses receiving a better product or service through AI-agent automation
* **Service providers**: APIs, data providers, developers, platforms, marketplaces, or other participants that can transact directly with agents
* **Ecosystem stakeholders**: Developers and businesses exploring new AI-native products and machine-to-machine commerce on XRPL

---

## 🎯 What You're Building

The challenge is to move from:

> **"How can I make an AI agent send a transaction?"**

to:

> **"What becomes possible when an AI agent can independently discover, decide, transact, and deliver value?"**

```text
┌──────────────────────────────────────────────────────────────┐
│                       Customer Need                          │
│        Objective • Request • Budget • Constraints            │
└────────────────────────────┬─────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────┐
│                         AI Agent                             │
│         Discover • Compare • Reason • Decide • Act           │
└────────────────────────────┬─────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────┐
│                  Agentic Transaction Layer                   │
│    XRPL AI Starter Kit • XRPL • x402 / MPP (recommended)     │
└────────────────────────────┬─────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────┐
│                     Commercial Outcome                       │
│        Purchase • Access • Execute • Deliver • Settle        │
└──────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Key Capabilities

### 1. AI Agent Orchestration

Use an AI agent to understand a customer or business objective and determine what actions are required to fulfil it.

### 2. Service Discovery

Enable the agent to discover or select relevant products, services, APIs, data sources, or counterparties based on the objective.

### 3. Agentic Decision-Making

Allow the agent to compare available options and make an autonomous or user-authorised economic decision.

### 4. Machine-to-Machine Payments (recommended)

Recommended: use an agentic payment standard such as **x402**, **MPP**, or another agentic payment standard as part of the agent workflow to enable machine-to-machine payment for a product, service, API, resource, or other economically meaningful action. This is recommended where it fits your solution, but it is not a hard requirement.

### 5. XRPL Integration

Enable the agent to interact with XRPL-related functionality and execute at least one successful XRPL transaction. The **XRPL AI Starter Kit** is recommended for this, but not required.

### 6. Commercial Loop

Demonstrate what is purchased, who pays, who receives value, what is delivered in return, and why the agent improves the experience.

---

## 🧠 Agent & Commercial Inputs

The solution should demonstrate how the agent uses relevant context to make useful decisions.

Potential inputs include:

* Customer or business objective
* User preferences
* Budget or spending constraints
* Available services or providers
* Pricing
* Service quality or performance
* API or resource availability
* Transaction requirements
* Payment conditions
* Previous agent actions or outcomes

The objective is not simply to automate a payment, but to demonstrate **why the agent chooses to transact and what value the transaction unlocks**.

---

## 🔄 Example Commercial Flow

```text
Customer Need
      ↓
AI Agent Understands the Objective
      ↓
Discover / Compare Services
      ↓
Agent Selects an Appropriate Option
      ↓
Agentic Payment (x402 / MPP recommended)
      ↓
XRPL Transaction / Settlement
      ↓
Product, Service or Value Delivered
```

A strong solution should demonstrate how the agent moves from **need → discovery → decision → transaction → outcome**.

---

## 🛡️ Trust, Governance & Agent Controls

AI agents making economic decisions should operate within clear and understandable boundaries.

Participants should consider:

* **Transparency** — Can users understand what the agent is doing and why?
* **Authorisation** — Which actions can the agent perform autonomously?
* **Spending controls** — Are appropriate limits or permissions in place?
* **Security** — How are wallets, credentials, APIs, and transaction permissions protected?
* **Traceability** — Can agent decisions and transactions be inspected?
* **Failure handling** — What happens if a transaction, service, or agent action fails?
* **Safeguards** — How does the solution prevent unintended or inappropriate transactions?

Agent autonomy should create a better product experience without sacrificing appropriate user control.

---

## 🛠️ Technology

Participants may use **any technology stack, APIs, AI models, frameworks, software, or hardware** suitable for their solution.

The only required component is the **XRP Ledger (XRPL)**, as long as the submission pertains to agentic payment:

* **XRP Ledger (XRPL)** (required)

The following are recommended and encouraged where they fit your solution, but they are not hard requirements:

* **XRPL AI Starter Kit** (recommended)
* Agentic payment standards such as **x402**, **MPP**, and other agentic standards (recommended)

The prototype must demonstrate at least **one successful XRPL transaction**.

> **⛔ XRPL only for the blockchain part.** All on-chain functionality must run on the XRP Ledger (Mainnet, Testnet, or Devnet). The **XRPL EVM Sidechain is not an option** for this challenge. Any smart contract or blockchain logic built on the EVM Sidechain, or on any other EVM or non-XRPL chain, does not count toward the requirements and will not be judged as valid XRPL integration.

Solutions should consider how the proposed technology could realistically operate beyond the prototype, including:

* Security
* Scalability
* Performance
* Reliability
* Infrastructure requirements
* Cost
* Integration
* Compliance where relevant

---

## 🏆 Judging Criteria

| Criteria                     | Weight | Description                                                                                                                                                       |
| ---------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Reachability**             | 20%    | Potential for broad adoption across customers, sectors, and use cases, including interoperability, developer accessibility, scalability, and compliance readiness |
| **Creativity**               | 20%    | Degree to which the solution introduces an innovative AI-native product, workflow, or business model through the use of the XRPL AI Starter Kit and, where it fits, recommended agentic payment standards such as x402 or MPP          |
| **Feasibility**              | 20%    | Realism of implementation in a production environment, including cost, performance, infrastructure readiness, reliability, and operational considerations         |
| **Technical Depth**          | 20%    | Quality and sophistication of the XRPL and agent integrations (and any agentic payment standards such as x402 or MPP, where used), including architecture, security, autonomy, testing, and safeguards                         |
| **User Experience & Design** | 10%    | Clarity, usability, and polish of the end-to-end experience, including how clearly agent actions, payments, and on-chain transactions are communicated            |
| **Builder Feedback**         | 10%     | Completeness and usefulness of feedback on the XRPL development experience, including the AI Starter Kit, practical challenges, and mainnet readiness             |

---

## 📝 Builder Feedback

Participants should provide short, constructive feedback based on their experience building the solution.

There are two things you need to do here, and they work together:

1. **Keep the feedback hooks running throughout the build.** Set up the feedback hook (see the top of this README) and leave it on for the whole hackathon. It pushes your builder feedback automatically and consistently as you work, so your feedback reflects the real development experience instead of a single end-of-event recollection. Consistent automated feedback is what secures your feedback score.
2. **Submit the Google form near the end of the hackathon.** Once your build is mostly done and you have a full picture of the XRPL development experience, submit the final feedback form: [https://forms.gle/FZckiEAMU8oWXVbX7]

In short: let the hooks push feedback continuously during the build, then submit the Google form as your final wrap-up near the end.
---

## ✅ Features Checklist

### Product & Commercial Proposition

* Clear customer problem
* Defined target user or customer
* Clear product proposition
* Meaningful role for the AI agent
* Credible commercial or business model

### Agent & Transaction Flow

* Working AI-agent workflow
* Agent discovery or decision-making
* XRPL AI Starter Kit integration (recommended)
* Agentic payment standard such as x402 or MPP (recommended)
* At least one successful XRPL transaction
* Product, service, or value delivered after the transaction

### Submission

* Public GitHub repository
* Source code
* Setup instructions
* Product overview
* Architecture diagram
* XRPL transaction hashes or explorer references
* Explanation of the XRPL AI Starter Kit integration if used (recommended)
* Explanation of the agentic payment flow if a recommended agentic payment standard such as x402 or MPP is used
* Builder feedback completed

---

## 🎤 Submission & Demo

**Format**: Working Prototype + Public GitHub Repository

Your final submission should include:

* Clear articulation of the customer problem
* Clear representation of the proposed product or service
* Explanation of how the AI agent creates value
* Demonstration of the core customer journey
* Demonstration of the agentic transaction flow
* At least one successful XRPL transaction
* Explanation of the XRPL AI Starter Kit integration if used (recommended)
* Explanation of how any recommended agentic payment standard such as x402 or MPP is used, if applicable
* Architecture diagram
* Transaction hashes or explorer references

The submission should be **concise, comprehensive, and easy to follow**, with enough information for reviewers to understand what you built, how it works, and how the core experience can be reproduced.

---

## 🚀 Challenge North Star

> **Don't just make an agent that can pay. Build a business because agents can pay.**

Build something where removing the AI agent or removing autonomous payments would fundamentally weaken the product.
