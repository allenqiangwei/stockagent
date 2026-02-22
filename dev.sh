#!/bin/bash
#
# 开发启动脚本 — 同时启动 FastAPI 后端 + Next.js 前端
#

cd "$(dirname "${BASH_SOURCE[0]}")"

export NO_PROXY=localhost,127.0.0.1

# 激活虚拟环境
source venv/bin/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null

echo "🚀 启动 StockAgent v2..."
echo ""

# 启动后端
echo "📡 Backend → http://127.0.0.1:8050"
uvicorn api.main:app --host 0.0.0.0 --port 8050 &
BACKEND_PID=$!

# 启动前端
echo "🌐 Frontend → http://0.0.0.0:3050"
(cd web && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号，清理子进程
trap "echo ''; echo '⏹ 停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

wait
