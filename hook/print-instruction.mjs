#!/usr/bin/env node
// Prints the shared XRPL feedback instruction with the resolved submit.mjs
// path. Use this to get the exact text to paste into an agent's instructions
// or rules file when that agent has no stop hook that can inject.
//
//   node print-instruction.mjs

import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildInstruction } from "./reflection.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const submitPath = path.resolve(here, "submit.mjs");
process.stdout.write(buildInstruction(submitPath) + "\n");
