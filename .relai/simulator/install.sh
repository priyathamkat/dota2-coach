#!/usr/bin/env bash
set -euo pipefail

# RELAI managed requirements:
# - use .relai/simulator/.venv as the simulator-local environment
# - do not require ROOT_DIR/.venv
# - preserve RELAI_REQUIRE_OPTIMIZER_BACKEND support
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SIM_DIR="$ROOT_DIR/.relai/simulator"
VENV_DIR="$SIM_DIR/.venv"
REQUIRE_OPTIMIZER_BACKEND="${RELAI_REQUIRE_OPTIMIZER_BACKEND:-0}"
export UV_CACHE_DIR="$SIM_DIR/.uv-cache"

require_command() {
  local command_name="$1"
  local message="${2:-$command_name is required but not installed.}"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "$message" >&2
    exit 1
  fi
}

require_relai_simulator_python() {
  local python_bin="$1"
  if [ ! -x "$python_bin" ]; then
    echo "RELAI simulator Python was not found at $python_bin." >&2
    exit 1
  fi
  "$python_bin" - <<'PY'
import platform
import sys

if sys.version_info < (3, 11):
    raise SystemExit(
        "RELAI simulator requires Python 3.11 or newer, but the simulator venv is "
        f"running Python {platform.python_version()} at {sys.executable}. "
        "Install uv or make a separate Python 3.11+ interpreter available, then rerun relai init."
    )
PY
}


# BEGIN RELAI CLI SDK INSTALL - do not edit
read_relai_config_value() {
  if [ -z "${RELAI_CONFIG_PYTHON:-}" ] || [ ! -x "$RELAI_CONFIG_PYTHON" ]; then
    echo "RELAI simulator config reader requires a validated simulator venv Python." >&2
    exit 1
  fi
  "$RELAI_CONFIG_PYTHON" - "$ROOT_DIR/.relai/config.toml" "$1" "$2" <<'PY'
import sys
import tomllib

path, section, key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "rb") as file:
    config = tomllib.load(file)
value = config.get(section, {}).get(key)
if not value:
    raise SystemExit(f"missing {section}.{key} in {path}")
print(value)
PY
}

read_optional_relai_config_value() {
  if [ -z "${RELAI_CONFIG_PYTHON:-}" ] || [ ! -x "$RELAI_CONFIG_PYTHON" ]; then
    echo "RELAI simulator config reader requires a validated simulator venv Python." >&2
    exit 1
  fi
  "$RELAI_CONFIG_PYTHON" - "$ROOT_DIR/.relai/config.toml" "$1" "$2" <<'PY'
import sys
import tomllib

path, section, key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "rb") as file:
    config = tomllib.load(file)
value = config.get(section, {}).get(key, "")
print(value or "")
PY
}

resolve_relai_sdk_spec() {
  RELAI_SDK_LOCAL_PATH="${RELAI_SDK_LOCAL_PATH:-$(read_optional_relai_config_value local relai_sdk_path)}"
  if [ -n "$RELAI_SDK_LOCAL_PATH" ]; then
    if [ ! -f "$RELAI_SDK_LOCAL_PATH/pyproject.toml" ]; then
      echo "local RELAI Python SDK pyproject.toml not found at $RELAI_SDK_LOCAL_PATH/pyproject.toml" >&2
      exit 1
    fi
    if [ ! -f "$RELAI_SDK_LOCAL_PATH/src/relai/__init__.py" ]; then
      echo "local RELAI Python SDK package not found at $RELAI_SDK_LOCAL_PATH/src/relai" >&2
      exit 1
    fi
    echo "$RELAI_SDK_LOCAL_PATH"
    return
  fi

  local metadata
  local sdk_version
  metadata="$(resolve_relai_sdk_metadata)"
  sdk_version="$(resolve_relai_sdk_version "$metadata")"
  if [ -n "$sdk_version" ]; then
    echo "relai==$sdk_version"
    return
  fi

  local download_url
  download_url="$(printf '%s' "$metadata" | jq -r '.download_url // empty')"
  if [ -n "$download_url" ]; then
    printf '%s\n' "$download_url"
    return
  fi

  echo "RELAI SDK metadata must include version or download_url." >&2
  exit 1
}

resolve_relai_sdk_metadata() {
  require_command curl
  require_command jq
  RELAI_API_URL="$(read_relai_config_value api url)"
  RELAI_API_KEY="$(read_relai_config_value api key)"
  curl -fsSL \
    -H "Authorization: Token ${RELAI_API_KEY}" \
    "${RELAI_API_URL%/}/sdk-url"
}

resolve_relai_sdk_version() {
  local metadata="${1:-}"
  local version
  if [ -z "$metadata" ]; then
    metadata="$(resolve_relai_sdk_metadata)"
  fi
  version="$(printf '%s' "$metadata" | jq -r '.version // empty')"
  printf '%s\n' "$version"
}

resolve_relai_sdk_index_url() {
  RELAI_API_URL="$(read_relai_config_value api url)"
  printf '%s/sdk/simple/\n' "${RELAI_API_URL%/}"
}

resolve_relai_agent_backend_path() {
  printf '%s\n' "${RELAI_AGENT_BACKEND_LOCAL_PATH:-$(read_optional_relai_config_value local relai_agent_backend_path)}"
}

relai_sdk_spec_is_local() {
  [ -n "${RELAI_SDK_LOCAL_PATH:-$(read_optional_relai_config_value local relai_sdk_path)}" ]
}

current_relai_sdk_version() {
  local python_bin="$1"
  if [ ! -x "$python_bin" ]; then
    return
  fi
  "$python_bin" - <<'PY'
from importlib.metadata import PackageNotFoundError, version

try:
    print(version("relai"))
except PackageNotFoundError:
    pass
PY
}

configure_relai_sdk_index_auth() {
  RELAI_API_KEY="$(read_relai_config_value api key)"
  export UV_INDEX_RELAI_USERNAME="${UV_INDEX_RELAI_USERNAME:-__token__}"
  export UV_INDEX_RELAI_PASSWORD="$RELAI_API_KEY"
  export POETRY_HTTP_BASIC_RELAI_USERNAME="${POETRY_HTTP_BASIC_RELAI_USERNAME:-__token__}"
  export POETRY_HTTP_BASIC_RELAI_PASSWORD="${POETRY_HTTP_BASIC_RELAI_PASSWORD:-$RELAI_API_KEY}"
}

relai_sdk_index_url_with_credentials() {
  local url="$1"
  local key="$2"
  case "$url" in
    https://*) printf 'https://__token__:%s@%s\n' "$key" "${url#https://}" ;;
    http://*) printf 'http://__token__:%s@%s\n' "$key" "${url#http://}" ;;
    *) printf '%s\n' "$url" ;;
  esac
}

mark_relai_sdk_uv_index_explicit() {
  local python_bin="$1"
  "$python_bin" - "$SIM_DIR/pyproject.toml" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
index = 0
while index < len(lines):
    if lines[index].strip() != "[[tool.uv.index]]":
        index += 1
        continue
    block_start = index
    index += 1
    while index < len(lines) and not lines[index].lstrip().startswith("["):
        index += 1
    block_end = index
    block = lines[block_start:block_end]
    if not any(line.strip() in {'name = "relai"', "name = 'relai'"} for line in block):
        continue
    for line_index in range(block_start + 1, block_end):
        if lines[line_index].strip().startswith("explicit"):
            lines[line_index] = "explicit = true\n"
            path.write_text("".join(lines))
            raise SystemExit(0)
    insert_at = block_end
    while insert_at > block_start + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    lines.insert(insert_at, "explicit = true\n")
    path.write_text("".join(lines))
    raise SystemExit(0)

raise SystemExit("RELAI uv index not found in pyproject.toml")
PY
}

install_relai_sdk_with_uv_index() {
  local python_bin="$1"
  local sdk_version="$2"
  local sdk_index_url="$3"
  local installed_version
  uv add --frozen "relai==$sdk_version" --index "relai=$sdk_index_url"
  mark_relai_sdk_uv_index_explicit "$python_bin"
  installed_version="$(current_relai_sdk_version "$python_bin")"
  if [ "$installed_version" = "$sdk_version" ]; then
    echo "RELAI SDK $sdk_version is already installed; skipping SDK install."
    return
  fi
  uv sync --python "$python_bin" --no-install-project
}

install_relai_sdk() {
  local python_bin="$1"
  local manager="$2"
  local sdk_spec
  local sdk_version
  local installed_version
  local sdk_index_url
  sdk_spec="$(resolve_relai_sdk_spec)"
  if relai_sdk_spec_is_local; then
    if [ "$manager" = "uv" ]; then
      uv add "$sdk_spec"
    else
      "$python_bin" -m pip install "$sdk_spec"
    fi
    return
  fi

  case "$sdk_spec" in
    http://*|https://*)
      if [ "$manager" = "uv" ]; then
        uv pip install --python "$python_bin" "$sdk_spec"
      else
        "$python_bin" -m pip install "$sdk_spec"
      fi
      return
      ;;
  esac

  sdk_version="${sdk_spec#relai==}"
  configure_relai_sdk_index_auth
  sdk_index_url="$(resolve_relai_sdk_index_url)"
  if [ "$manager" = "uv" ]; then
    install_relai_sdk_with_uv_index "$python_bin" "$sdk_version" "$sdk_index_url"
  elif [ "$manager" = "poetry" ]; then
    installed_version="$(current_relai_sdk_version "$python_bin")"
    if [ "$installed_version" = "$sdk_version" ]; then
      echo "RELAI SDK $sdk_version is already installed; skipping SDK install."
      return
    fi
    poetry source remove relai >/dev/null 2>&1 || true
    poetry source add --priority explicit relai "$sdk_index_url"
    poetry add "relai==$sdk_version" --source relai
  else
    installed_version="$(current_relai_sdk_version "$python_bin")"
    if [ "$installed_version" = "$sdk_version" ]; then
      echo "RELAI SDK $sdk_version is already installed; skipping SDK install."
      return
    fi
    "$python_bin" -m pip install --extra-index-url "$(relai_sdk_index_url_with_credentials "$sdk_index_url" "$RELAI_API_KEY")" "relai==$sdk_version"
  fi
}

# END RELAI CLI SDK INSTALL

cd "$SIM_DIR"

require_command uv

if [ -x "$VENV_DIR/bin/python" ] && ! "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import sys
PY
then
  rm -rf "$VENV_DIR"
fi

if [ "$REQUIRE_OPTIMIZER_BACKEND" = "1" ]; then
  require_command python3.12 "relai optimize local-dev backend mode requires python3.12 to install relai_agent_backend."
  if [ -x "$VENV_DIR/bin/python" ] && ! "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)
PY
  then
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  if [ "$REQUIRE_OPTIMIZER_BACKEND" = "1" ]; then
    uv venv --python python3.12 "$VENV_DIR"
  else
    uv venv "$VENV_DIR"
  fi
fi
require_relai_simulator_python "$VENV_DIR/bin/python"
export RELAI_CONFIG_PYTHON="$VENV_DIR/bin/python"

# BEGIN RELAI CLI SDK INSTALL - do not edit
install_relai_sdk "$VENV_DIR/bin/python" uv
# END RELAI CLI SDK INSTALL
# BEGIN PROJECT DEPENDENCY INSTALL
uv pip install --python "$VENV_DIR/bin/python" -e "$ROOT_DIR"
# END PROJECT DEPENDENCY INSTALL
uv pip install --python "$VENV_DIR/bin/python" -e "$SIM_DIR"
if [ "$REQUIRE_OPTIMIZER_BACKEND" = "1" ]; then
  BACKEND_PATH="$(resolve_relai_agent_backend_path)"
  if [ -z "$BACKEND_PATH" ]; then
    echo "relai optimize local-dev backend mode requires RELAI_AGENT_BACKEND_LOCAL_PATH or local.relai_agent_backend_path in $ROOT_DIR/.relai/config.toml." >&2
    exit 1
  fi
  if [ ! -f "$BACKEND_PATH/pyproject.toml" ]; then
    echo "relai optimize local-dev backend mode requires a local relai-agent-backend checkout at $BACKEND_PATH." >&2
    exit 1
  fi
  uv pip install --python "$VENV_DIR/bin/python" -e "$BACKEND_PATH"
fi
