#!/bin/bash
# Daily run for LuckyHands Intel Daily.
# Triggered by ~/Library/LaunchAgents/com.luckyhands.intel_daily.plist.

set -e
set -o pipefail

PROJECT_ROOT="/Users/ritzmish/intel_daily"
LOG_DIR="${PROJECT_ROOT}/logs"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# Make sure Homebrew binaries are on PATH for launchd.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"
export INTEL_DAILY_NO_BROWSER=1

cd "${PROJECT_ROOT}"

mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/daily.log"

echo "" >> "${LOG}"
echo "============================================================" >> "${LOG}"
echo "[${TIMESTAMP}] daily run starting" >> "${LOG}"
echo "============================================================" >> "${LOG}"

# Make sure Ollama is up. brew services starts it at boot, but check.
if ! curl -s --max-time 3 http://localhost:11434/api/tags > /dev/null; then
  echo "[${TIMESTAMP}] Ollama not reachable, starting via brew services" >> "${LOG}"
  /opt/homebrew/bin/brew services start ollama >> "${LOG}" 2>&1 || true
  sleep 5
fi

# Activate venv and run pipeline.
source "${PROJECT_ROOT}/.venv/bin/activate"
python "${PROJECT_ROOT}/run.py" slack >> "${LOG}" 2>&1

END_TS=$(date "+%Y-%m-%d %H:%M:%S")
echo "[${END_TS}] daily run finished" >> "${LOG}"
