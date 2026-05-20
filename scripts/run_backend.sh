#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    echo "错误：未找到 .venv 虚拟环境，请先运行 ./scripts/setup_backend.sh"
    exit 1
fi

echo "=== 启动 LocalLife Agent 后端 ==="
echo "服务地址: http://127.0.0.1:8000"
echo "健康检查: http://127.0.0.1:8000/health"
echo "API 文档:  http://127.0.0.1:8000/docs"
echo ""

.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
