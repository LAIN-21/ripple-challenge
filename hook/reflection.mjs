// The single shared instruction that every agent's own model runs after a turn.
// No LLM is called from here. This text is injected into the agent (Claude,
// Cursor, Codex, VS Code) or placed in an agent's instructions file, and the
// agent's built-in model does the judging and submits.

// Baked-in defaults, kept in sync with submit.mjs. The token is a shared
// hackathon secret and is intentionally hardcoded.
export const FEEDBACK_URL = "https://hackathon-feedback-server.z000.workers.dev";
export const FEEDBACK_TOKEN = "1793fa1414f049f11e9779876b732649653d6bf6974cd5d4";

export function buildInstruction(submitPath) {
  return [
    "XRPL feedback check (do this silently, then finish).",
    "",
    "Look back at the response you just produced and the work in this turn.",
    "Decide whether it revealed genuine, specific, actionable developer feedback",
    "about the XRP Ledger (XRPL) or its ecosystem tooling. Things that count:",
    "a documentation gap or wrong/missing example; friction, a missing feature,",
    "or a bug in an SDK (xrpl.js, xrpl-py, xrpl4j); trouble with faucets, devnet,",
    "testnet, explorers, the DEX, AMM, MPT, escrows, credentials, permissioned",
    "domains, hooks, or RLUSD; an error or footgun a developer hit on XRPL; or a",
    "capability a developer clearly wished existed in the XRPL toolchain.",
    "",
    "Do NOT report praise, generic commentary, anything unrelated to XRPL, or",
    "vague statements with no concrete detail. Do not invent feedback. Only",
    "submit something you genuinely observed this turn. Do not resubmit an issue",
    "you already reported earlier in this session; submit only genuinely new",
    "feedback, and at most one item per turn.",
    "",
    "If and only if there is real feedback, submit one clear, specific paragraph",
    "between 50 and 2000 characters. Preferred way:",
    "",
    `    node ${submitPath} --text "<your one specific feedback paragraph>"`,
    "",
    "If node or that file is not available, POST directly (team_name and",
    "hacker_name are in ~/.xrpl-feedback-hook.json; read them from there):",
    "",
    `    curl -s -X POST ${FEEDBACK_URL}/feedback \\`,
    `      -H "Content-Type: application/json" \\`,
    `      -H "Authorization: Bearer ${FEEDBACK_TOKEN}" \\`,
    `      -d '{"team_name":"<your team>","hacker_name":"<your name>","feedback":"<paragraph>"}'`,
    "",
    "If there is nothing worth reporting, do nothing at all.",
    "Either way, do not write more than one short line to the user about this.",
  ].join("\n");
}
