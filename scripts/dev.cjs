#!/usr/bin/env node

const { spawn } = require("child_process");
const { existsSync } = require("fs");
const { join } = require("path");

const root = process.cwd();
const candidates = [
  join(root, ".venv", "bin", "python"),
  join(root, ".venv", "bin", "python3"),
  process.env.PYTHON,
  "python3",
  "python",
].filter(Boolean);

function resolvePython() {
  for (const candidate of candidates) {
    if (candidate.startsWith("/") || candidate.startsWith(".")) {
      if (existsSync(candidate)) {
        return candidate;
      }
      continue;
    }
    return candidate;
  }
  return "python3";
}

const python = resolvePython();
const child = spawn(python, ["app/main.py"], {
  cwd: root,
  stdio: "inherit",
  env: {
    ...process.env,
    PYTHONUNBUFFERED: "1",
  },
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
