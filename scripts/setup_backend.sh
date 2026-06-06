#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== LocalLife Agent 后端环境初始化 ==="

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "[1/3] 创建 .venv 虚拟环境..."
    python3 -m venv .venv
else
    echo "[1/3] .venv 已存在，跳过创建"
fi

# 激活虚拟环境
source .venv/bin/activate

# 升级 pip
echo "[2/3] 升级 pip..."
.venv/bin/pip install --upgrade pip -q

# 安装依赖
echo "[3/3] 安装后端依赖..."
.venv/bin/pip install -r backend/requirements.txt -q

echo ""
echo "=== 初始化完成 ==="
echo ""
echo "启动后端："
echo "  ./scripts/run_backend.sh"
echo ""
echo "或手动启动："
echo "  source .venv/bin/activate"
echo "  .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"
