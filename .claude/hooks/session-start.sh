#!/bin/bash
# Prepara sessões do Claude Code na nuvem: uv + dependências travadas. Nunca lê .env.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

if ! command -v uv >/dev/null 2>&1; then
  pip install --quiet uv
fi

uv sync --frozen

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export LIVE_MODE=false" >> "$CLAUDE_ENV_FILE"
fi
