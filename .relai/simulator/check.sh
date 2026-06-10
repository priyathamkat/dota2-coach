#!/usr/bin/env bash
set -euo pipefail

# RELAI managed requirements:
# - validate the simulator-local venv, not ROOT_DIR/.venv
# - preserve RELAI_REQUIRE_OPTIMIZER_BACKEND support
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SIM_DIR="$ROOT_DIR/.relai/simulator"
VENV_PYTHON="$SIM_DIR/.venv/bin/python"
REQUIRE_OPTIMIZER_BACKEND="${RELAI_REQUIRE_OPTIMIZER_BACKEND:-0}"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Simulator virtualenv is missing. Run .relai/simulator/install.sh" >&2
  exit 1
fi

PYTHONPATH="$SIM_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
"$VENV_PYTHON" - <<'PY'
import importlib
import os
import sys

for module_name in [
    "relai",
    "relai_simulator",
    "dota2_coach",
    "langchain",
    "langgraph",
    "langchain_anthropic",
]:
    importlib.import_module(module_name)
if os.environ.get("RELAI_REQUIRE_OPTIMIZER_BACKEND") == "1":
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("relai optimize local-dev backend mode requires a simulator venv running Python 3.12.")
    importlib.import_module("relai_agent_backend.optimizer")
PY
