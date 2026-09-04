#!/usr/bin/env bash
# Quick manual matter lookup, bypassing the Claude CLI entirely — a workaround
# for the platform bug where Claude sessions substitute a stale, unreachable
# Maton credential for clio-toolkit skills regardless of the real env value.
# Usage: ./check-matter.sh "Hines,Nathan"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ANALYZE_SCRIPT="$HOME/.claude/plugins/marketplaces/local-desktop-app-uploads/clio-toolkit/skills/clio-matter-analysis/scripts/analyze_matter.py"

if [ $# -lt 1 ]; then
  echo "Usage: $0 \"<matter query>\"" >&2
  echo 'Example: ./check-matter.sh "Hines,Nathan"' >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ -z "${MATON_API_KEY:-}" ]; then
  echo "MATON_API_KEY is not set in $ENV_FILE" >&2
  exit 1
fi

python3 "$ANALYZE_SCRIPT" "$1" --connection "${CLIO_CONNECTION_ID:-}" | python3 -m json.tool
