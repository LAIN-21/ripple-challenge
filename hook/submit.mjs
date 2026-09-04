#!/usr/bin/env node
// POST-only feedback submitter. This is the ONLY piece that touches the
// network, and it only ever talks to the hackathon feedback server.
//
// The agent's own model calls this after it decides a turn revealed real
// XRPL developer feedback:
//     node submit.mjs --text "one specific paragraph of feedback"
// or:
//     echo "the feedback" | node submit.mjs
//
// It reads team name, real name, server URL, and token from
// ~/.xrpl-feedback-hook.json (env vars override). No LLM is called here.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

const FEEDBACK_MIN = 50;
const FEEDBACK_MAX = 2000;

// Baked-in hackathon defaults. The token is a shared hackathon secret and is
// intentionally hardcoded so the hook works with zero token setup. A config
// file or env var can still override both.
const DEFAULT_FEEDBACK_URL = "https://hackathon-feedback-server.z000.workers.dev";
const DEFAULT_FEEDBACK_TOKEN = "1793fa1414f049f11e9779876b732649653d6bf6974cd5d4";

function loadConfig() {
  const cfg = {
    feedbackUrl: process.env.FEEDBACK_URL,
    feedbackToken: process.env.FEEDBACK_TOKEN,
    teamName: process.env.TEAM_NAME,
    hackerName: process.env.HACKER_NAME,
  };
  const configPath =
    process.env.XRPL_FEEDBACK_CONFIG ||
    path.join(os.homedir(), ".xrpl-feedback-hook.json");
  try {
    if (fs.existsSync(configPath)) {
      const fileCfg = JSON.parse(fs.readFileSync(configPath, "utf8"));
      cfg.feedbackUrl = cfg.feedbackUrl || fileCfg.feedbackUrl;
      cfg.feedbackToken = cfg.feedbackToken || fileCfg.feedbackToken;
      cfg.teamName = cfg.teamName || fileCfg.teamName;
      cfg.hackerName = cfg.hackerName || fileCfg.hackerName;
    }
  } catch (err) {
    fail("could not read config: " + String(err));
  }
  cfg.feedbackUrl = cfg.feedbackUrl || DEFAULT_FEEDBACK_URL;
  cfg.feedbackToken = cfg.feedbackToken || DEFAULT_FEEDBACK_TOKEN;
  return cfg;
}

function fail(msg) {
  process.stderr.write("xrpl-feedback submit: " + msg + "\n");
  process.exit(1);
}

function getFeedbackText() {
  const i = process.argv.indexOf("--text");
  if (i !== -1 && process.argv[i + 1]) return process.argv[i + 1];
  try {
    const stdin = fs.readFileSync(0, "utf8");
    if (stdin.trim()) return stdin;
  } catch {
    // no stdin
  }
  return "";
}

// Normalize so trivial rewordings (case, punctuation, spacing) dedupe too.
function normalizeForDedup(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

// Avoid sending the same or a near-identical feedback twice.
function isDuplicate(feedback) {
  try {
    const statePath = path.join(os.tmpdir(), "xrpl-feedback-submit.state");
    const hash = crypto.createHash("sha256").update(normalizeForDedup(feedback)).digest("hex");
    let seen = [];
    if (fs.existsSync(statePath)) seen = JSON.parse(fs.readFileSync(statePath, "utf8"));
    if (seen.includes(hash)) return true;
    seen.push(hash);
    fs.writeFileSync(statePath, JSON.stringify(seen.slice(-200)));
    return false;
  } catch {
    return false;
  }
}

async function main() {
  const cfg = loadConfig();
  const missing = [];
  if (!cfg.teamName) missing.push("teamName");
  if (!cfg.hackerName) missing.push("hackerName");
  if (missing.length) fail("missing config: " + missing.join(", ") + ". Run setup.mjs.");

  let feedback = getFeedbackText().trim();
  if (!feedback) fail("no feedback text provided");
  if (feedback.length < FEEDBACK_MIN) fail(`feedback must be at least ${FEEDBACK_MIN} characters`);
  if (feedback.length > FEEDBACK_MAX) feedback = feedback.slice(0, FEEDBACK_MAX);

  if (isDuplicate(feedback)) {
    process.stdout.write("skipped: duplicate feedback already submitted this session\n");
    process.exit(0);
  }

  const url = cfg.feedbackUrl.replace(/\/$/, "") + "/feedback";
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${cfg.feedbackToken}`,
      },
      body: JSON.stringify({
        team_name: cfg.teamName,
        hacker_name: cfg.hackerName,
        feedback,
      }),
    });
  } catch (err) {
    fail("network error: " + String(err));
  }

  const bodyText = await res.text().catch(() => "");
  if (res.status === 201) {
    process.stdout.write("feedback submitted\n");
    process.exit(0);
  }
  fail(`server returned ${res.status}: ${bodyText}`);
}

main().catch((err) => fail(String(err)));
