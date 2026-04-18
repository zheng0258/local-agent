#!/bin/bash
# judge-server.sh — 啟動 / 停止 / 狀態確認 judge LLM server
#
# 用法：
#   ./scripts/judge-server.sh start    # 啟動（若已在跑則略過）
#   ./scripts/judge-server.sh stop     # 停止
#   ./scripts/judge-server.sh restart  # 強制重啟
#   ./scripts/judge-server.sh status   # 確認狀態
#   ./scripts/judge-server.sh health   # 打 health check API

set -euo pipefail

# ── 設定 ─────────────────────────────────────────────────────────────
PORT="${JUDGE_LLM_PORT:-1235}"
LOG_FILE="/tmp/judge-server.log"
PID_FILE="/tmp/judge-server.pid"
STARTUP_WAIT=60   # 等待 model 載入秒數（本地路徑約 10–20 秒）

# LM Studio 本地路徑優先，避免重複下載
# 可用 JUDGE_LLM_MODEL 覆蓋（HuggingFace repo 名稱或本地路徑皆可）
LM_STUDIO_MODEL="${HOME}/.cache/lm-studio/models/mlx-community/gemma-4-e4b-it-4bit"
HF_CACHE_MODEL="${HOME}/.cache/huggingface/hub/models--mlx-community--gemma-4-e4b-it-4bit/snapshots"

_resolve_model() {
    if [ -n "${JUDGE_LLM_MODEL:-}" ]; then
        echo "${JUDGE_LLM_MODEL}"
    elif [ -d "${LM_STUDIO_MODEL}" ]; then
        echo "${LM_STUDIO_MODEL}"
    elif [ -d "${HF_CACHE_MODEL}" ]; then
        # 找最新的 snapshot
        echo "$(ls -td "${HF_CACHE_MODEL}"/*/  2>/dev/null | head -1)"
    else
        # fallback：從 HuggingFace 下載
        echo "mlx-community/gemma-4-e4b-it-4bit"
    fi
}

MODEL="$(_resolve_model)"

# ── 顏色輸出 ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[judge-server]${NC} $*"; }
warn()    { echo -e "${YELLOW}[judge-server]${NC} $*"; }
error()   { echo -e "${RED}[judge-server]${NC} $*"; }

# ── 函數 ─────────────────────────────────────────────────────────────
is_running() {
    lsof -ti:"${PORT}" > /dev/null 2>&1
}

wait_for_ready() {
    info "等待 server 就緒（最多 ${STARTUP_WAIT} 秒）..."
    for i in $(seq 1 "${STARTUP_WAIT}"); do
        if curl -s "http://localhost:${PORT}/v1/models" > /dev/null 2>&1; then
            info "Server 就緒（${i} 秒）"
            return 0
        fi
        sleep 1
    done
    error "Server 在 ${STARTUP_WAIT} 秒內未就緒，請查看 log：${LOG_FILE}"
    return 1
}

do_start() {
    if is_running; then
        warn "Port ${PORT} 已有 process 在跑，略過啟動"
        return 0
    fi

    info "啟動 judge server..."
    info "  Model : ${MODEL}"
    info "  Port  : ${PORT}"
    info "  Log   : ${LOG_FILE}"

    nohup python3 -m mlx_lm.server \
        --model "${MODEL}" \
        --port "${PORT}" \
        > "${LOG_FILE}" 2>&1 &

    echo $! > "${PID_FILE}"
    info "PID: $(cat "${PID_FILE}")"

    wait_for_ready
}

do_stop() {
    if ! is_running; then
        warn "Port ${PORT} 沒有 process 在跑"
        return 0
    fi

    local pid
    pid=$(lsof -ti:"${PORT}")
    info "停止 judge server（PID: ${pid}）..."
    kill "${pid}"

    # 等待 process 結束
    for i in $(seq 1 10); do
        if ! is_running; then
            info "Server 已停止"
            rm -f "${PID_FILE}"
            return 0
        fi
        sleep 1
    done

    warn "Process 未在 10 秒內結束，強制 kill..."
    kill -9 "${pid}" 2>/dev/null || true
    rm -f "${PID_FILE}"
}

do_status() {
    if is_running; then
        local pid
        pid=$(lsof -ti:"${PORT}")
        info "Running  (PID: ${pid}, Port: ${PORT})"
    else
        warn "Stopped  (Port: ${PORT} 無 process)"
    fi
}

do_health() {
    info "Health check → http://localhost:${PORT}/v1/models"
    if curl -s "http://localhost:${PORT}/v1/models" | python3 -m json.tool; then
        echo ""
        info "Server 正常回應"
    else
        error "Server 未回應"
        exit 1
    fi
}

# ── 主邏輯 ────────────────────────────────────────────────────────────
CMD="${1:-status}"

case "${CMD}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; sleep 2; do_start ;;
    status)  do_status ;;
    health)  do_health ;;
    *)
        echo "用法：$0 {start|stop|restart|status|health}"
        exit 1
        ;;
esac
