#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SKILL_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

if [[ -z "${CODEX_HOME:-}" ]]; then
  if [[ "$(basename -- "$(dirname -- "$SKILL_DIR")")" == "skills" ]]; then
    CODEX_HOME="$(cd -- "$SKILL_DIR/../.." && pwd -P)"
  else
    CODEX_HOME="$HOME/.codex"
  fi
fi
export CODEX_HOME

LOG_DIR="${RESEARCH_MAIL_DIGEST_LOG_DIR:-$CODEX_HOME/logs/research-mail-digest}"
WORKDIR="${RESEARCH_MAIL_DIGEST_WORKDIR:-$LOG_DIR/work}"
LOCK_FILE="$LOG_DIR/daily.lock"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/daily-$RUN_ID.log"
FINAL_FILE="$LOG_DIR/daily-$RUN_ID.final.md"

mkdir -p "$LOG_DIR" "$WORKDIR"

load_node_environment() {
  if command -v agently-cli >/dev/null 2>&1; then
    return 0
  fi

  local nvm_script="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  if [[ -s "$nvm_script" ]]; then
    # Load the user's default Node environment without pinning a host-specific Node version.
    # shellcheck disable=SC1090
    . "$nvm_script"
    nvm use --silent default >/dev/null 2>&1 || nvm use --silent node >/dev/null 2>&1 || true
  fi
}

if [[ ! -d "$WORKDIR" ]]; then
  echo "Configured workdir does not exist: $WORKDIR" >> "$LOG_FILE"
  exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another research-mail-digest job is already running." >> "$LOG_FILE"
  exit 0
fi

cd "$WORKDIR"

load_node_environment

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 not found in PATH; set PYTHON_BIN for this cron job." >> "$LOG_FILE"
  exit 1
fi

RUN_ARGS=(--workdir "$WORKDIR" --final-file "$FINAL_FILE")
if [[ "${RESEARCH_MAIL_DIGEST_DRY_RUN:-}" == "1" || "${RESEARCH_MAIL_DIGEST_DRY_RUN:-}" == "true" ]]; then
  RUN_ARGS+=(--dry-run)
fi

"$PYTHON_BIN" "$SCRIPT_DIR/run_daily_digest.py" "${RUN_ARGS[@]}" >> "$LOG_FILE" 2>&1
