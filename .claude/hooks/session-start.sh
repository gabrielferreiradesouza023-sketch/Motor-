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

# Worker (TypeScript): dependências travadas, se houver Node.
if command -v npm >/dev/null 2>&1 && [ -f worker/package-lock.json ]; then
  npm --prefix worker ci --no-audit --no-fund --silent
fi

# Render (T-26): ffmpeg/ffprobe e um Chromium. Sem eles, os testes de render são pulados.
if ! command -v ffmpeg >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
  (apt-get install -y -qq --no-install-recommends ffmpeg >/dev/null 2>&1 \
    || sudo -n apt-get install -y -qq --no-install-recommends ffmpeg >/dev/null 2>&1) || true
fi
chromium_path="$(command -v chromium || command -v chromium-browser || command -v google-chrome || true)"
if [ -z "$chromium_path" ]; then
  chromium_path="$(ls -d /opt/pw-browsers/chromium-*/chrome-linux*/chrome 2>/dev/null | head -1 || true)"
fi

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export LIVE_MODE=false" >> "$CLAUDE_ENV_FILE"
  if [ -n "$chromium_path" ]; then
    echo "export CHROMIUM_PATH=$chromium_path" >> "$CLAUDE_ENV_FILE"
  fi
fi
