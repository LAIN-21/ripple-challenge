// Shared sampling gate for the stop hooks. Decides whether the feedback check
// runs on this turn. Running on every single turn is disruptive and burns the
// developer's model quota, so the default is a fraction, not 1.
//
// Configure with "sample" (0 to 1) in ~/.xrpl-feedback-hook.json, or the
// XRPL_FEEDBACK_SAMPLE env var. 1 = every turn, 0 = never.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DEFAULT_SAMPLE = 0.2;

export function passesSampling() {
  let sample = process.env.XRPL_FEEDBACK_SAMPLE;
  if (sample === undefined || sample === "") {
    try {
      const cfgPath =
        process.env.XRPL_FEEDBACK_CONFIG ||
        path.join(os.homedir(), ".xrpl-feedback-hook.json");
      if (fs.existsSync(cfgPath)) {
        const s = JSON.parse(fs.readFileSync(cfgPath, "utf8")).sample;
        if (s !== undefined && s !== null && s !== "") sample = s;
      }
    } catch {
      // ignore, fall back to default
    }
  }

  let rate = Number(sample);
  if (sample === undefined || sample === null || sample === "" || Number.isNaN(rate)) {
    rate = DEFAULT_SAMPLE;
  }
  if (rate >= 1) return true;
  if (rate <= 0) return false;
  return Math.random() < rate;
}
