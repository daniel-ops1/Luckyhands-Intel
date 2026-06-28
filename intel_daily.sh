#!/bin/bash
# LuckyHands Intel Daily trigger script.
#
# Usage:
#   ./intel_daily.sh                Run pipeline. Then preview + verify + prompt before any Slack send.
#   ./intel_daily.sh --auto-slack   Run pipeline. Auto-post to Slack if verify gate passes (NO prompt).
#   ./intel_daily.sh --skip-run     Skip the pipeline run, just publish the latest existing brief.
#   ./intel_daily.sh --help         Show this message.
#
# What happens on the default flow:
#   1. Ollama + Gemini pipeline produces the brief.
#   2. intel_publish.py verifies every fact-bearing claim against the live web via
#      Gemini Flash + Google Search grounding.
#   3. You see the brief and the verify report in the terminal.
#   4. You pick: y to post to Slack, n to cancel, i to apply corrections and re-verify.
#   5. The loop repeats on i until you approve or cancel.

set -euo pipefail

PROJECT_DIR="/Users/ritzmish/intel_daily"
cd "$PROJECT_DIR"

MODE="interactive"
SKIP_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h)
      sed -n '/^# Usage/,/^# What/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --auto-slack)
      MODE="auto-slack"
      ;;
    --skip-run)
      SKIP_RUN=1
      ;;
    *)
      echo "Unknown flag: $1"
      echo "Try: $0 --help"
      exit 1
      ;;
  esac
  shift
done

mkdir -p output
LOG_FILE="output/run_$(date +%Y-%m-%d_%H%M%S).log"

echo "=========================================="
echo "  LuckyHands Intel Daily"
echo "=========================================="
echo "  Started:  $(date)"
echo "  Mode:     $MODE"
[ "$SKIP_RUN" -eq 1 ] && echo "  Pipeline: SKIPPED (--skip-run)"
echo "  Log:      $LOG_FILE"
echo "=========================================="
echo ""

source .venv/bin/activate

if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "ERROR Ollama is not reachable at http://localhost:11434"
  echo "Start it with: ollama serve"
  exit 1
fi

START_TS=$(date +%s)

if [ "$SKIP_RUN" -eq 0 ]; then
  if [ "$MODE" = "auto-slack" ]; then
    # Pipeline handles verify + Slack via the publisher_callback gate.
    PIPELINE_ENV_NO_SLACK=0
    PIPELINE_ENV_SKIP_VERIFY=0
  else
    # Interactive: pipeline must NOT post to Slack and must NOT auto-verify;
    # intel_publish.py handles verify + prompt.
    PIPELINE_ENV_NO_SLACK=1
    PIPELINE_ENV_SKIP_VERIFY=1
  fi

  set +e
  INTEL_DAILY_NO_SLACK="$PIPELINE_ENV_NO_SLACK" \
  INTEL_DAILY_SKIP_VERIFY="$PIPELINE_ENV_SKIP_VERIFY" \
  INTEL_DAILY_NO_BROWSER=1 \
    python run.py 2>&1 | tee "$LOG_FILE"
  PIPELINE_EXIT=${PIPESTATUS[0]}
  set -e

  if [ "$PIPELINE_EXIT" -ne 0 ]; then
    echo ""
    echo "Pipeline exited $PIPELINE_EXIT. Inspect: $LOG_FILE"
    exit "$PIPELINE_EXIT"
  fi
fi

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))
MM=$((ELAPSED / 60))
SS=$((ELAPSED % 60))

echo ""
echo "=========================================="
echo "  Pipeline done in ${MM}m ${SS}s"
echo "=========================================="

if [ "$MODE" = "auto-slack" ]; then
  # Auto mode: nothing more to do, publisher_callback already gated + posted.
  LATEST_VERIFY=$(ls -t output/verify_report_*.md 2>/dev/null | head -1 || true)
  [ -n "$LATEST_VERIFY" ] && echo "  Verify report: $LATEST_VERIFY"
  exit 0
fi

# Interactive: hand off to intel_publish.py
echo ""
echo "=========================================="
echo "  Handing off to interactive publisher"
echo "=========================================="
echo ""

python intel_publish.py
PUB_EXIT=$?

if [ "$PUB_EXIT" -ne 0 ]; then
  echo "intel_publish.py exited $PUB_EXIT"
fi
exit "$PUB_EXIT"
