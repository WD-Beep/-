#!/usr/bin/env bash
# 在云服务器「自报项目」根目录（与 server.py 同级）执行：
#   chmod +x scripts/redeploy_server.sh
#   bash scripts/redeploy_server.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/server.py" ]]; then
  echo "错误：未找到 $ROOT/server.py" >&2
  exit 1
fi

ENV_FILE="${QUOTE_ENV_FILE:-$ROOT/.env.prod}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "警告：未找到 $ENV_FILE，将使用当前 shell 环境变量。" >&2
fi

export QUOTE_SERVER_HOST="${QUOTE_SERVER_HOST:-0.0.0.0}"
export QUOTE_ADMIN_SERVER_HOST="${QUOTE_ADMIN_SERVER_HOST:-0.0.0.0}"
export QUOTE_SERVER_PORT="${QUOTE_SERVER_PORT:-8776}"
export QUOTE_ADMIN_HTTP_PORT="${QUOTE_ADMIN_HTTP_PORT:-8080}"
export KNOWLEDGE_AUTO_LEARN="${KNOWLEDGE_AUTO_LEARN:-1}"
export KNOWLEDGE_AUTO_WRITE="${KNOWLEDGE_AUTO_WRITE:-0}"
export KNOWLEDGE_PENDING_AUTO_APPLY="${KNOWLEDGE_PENDING_AUTO_APPLY:-1}"

FRONT_PORT="$QUOTE_SERVER_PORT"
ADMIN_PORT="$QUOTE_ADMIN_HTTP_PORT"
LOG="${QUOTE_SERVER_LOG:-$HOME/quote_server.log}"

echo "[1/4] 停止旧进程 (端口 $FRONT_PORT / $ADMIN_PORT)..."
pkill -f "python.*server.py" 2>/dev/null || true
sleep 2
for p in "$FRONT_PORT" "$ADMIN_PORT"; do
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${p}/tcp" 2>/dev/null || true
  fi
done
rm -f "$ROOT/.server.lock"* 2>/dev/null || true

echo "[2/4] 检查 Python 依赖..."
PYTHON="${PYTHON:-python3}"
if [[ -d "$ROOT/.venv/bin" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  PYTHON="python"
fi
if [[ "${SKIP_PIP_INSTALL:-0}" != "1" ]]; then
  if [[ "${QUOTE_DEPLOY_CPU_TORCH:-1}" == "1" ]]; then
    "$PYTHON" -m pip install -q "numpy>=1.24" "openpyxl>=3.1" "xlrd>=2.0" "psycopg[binary]>=3.1" \
      "langgraph>=0.2" "langchain-core>=0.3" 2>/dev/null || true
    "$PYTHON" -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu 2>/dev/null || true
    "$PYTHON" -m pip install -q "sentence-transformers>=3.0" 2>/dev/null || true
  else
    "$PYTHON" -m pip install -q -r requirements.txt 2>/dev/null || true
  fi
fi

if [[ -z "${OPENAI_API_KEY:-}" && -z "${MOONSHOT_API_KEY:-}" && -z "${KIMI_API_KEY:-}" ]]; then
  echo "Error: configure OPENAI_API_KEY (recommended) or MOONSHOT_API_KEY / KIMI_API_KEY in $ENV_FILE" >&2
  exit 1
fi

echo "[3/4] 启动服务 (前台 $FRONT_PORT / 后台 $ADMIN_PORT)..."
nohup "$PYTHON" server.py "$FRONT_PORT" >>"$LOG" 2>&1 &
NEW_PID=$!
sleep 4

echo "[4/4] 健康检查..."
FRONT_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${FRONT_PORT}/" || echo 000)"
ADMIN_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${ADMIN_PORT}/admin/login" || echo 000)"

echo "PID=$NEW_PID  LOG=$LOG"
echo "前台 HTTP $FRONT_CODE  -> http://$(curl -s ifconfig.me 2>/dev/null || echo 127.0.0.1):${FRONT_PORT}/"
echo "后台 HTTP $ADMIN_CODE -> http://$(curl -s ifconfig.me 2>/dev/null || echo 127.0.0.1):${ADMIN_PORT}/admin/login"

if [[ "$FRONT_CODE" != "200" || "$ADMIN_CODE" != "200" ]]; then
  echo "启动可能异常，请查看日志: tail -n 80 $LOG" >&2
  exit 1
fi

echo "部署完成。报价入库=data/quotes.db；回流=knowledge_updates/pending_auto_learn.jsonl + KNOWLEDGE_PENDING_AUTO_APPLY"
