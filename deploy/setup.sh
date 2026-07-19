#!/usr/bin/env bash
set -e

printf '==> Step 1: 创建 Python 虚拟环境\n'
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

printf '==> Step 2: 安装依赖\n'
pip install --upgrade pip
pip install -e ".[dev,factor,backtest,api,ui]"
playwright install chromium

printf '==> Step 3: 启动 PostgreSQL + Redis\n'
cd deploy
if docker compose version >/dev/null 2>&1; then
    docker compose up -d
else
    docker-compose up -d
fi
cd ..

printf '==> Step 4: 等待数据库就绪\n'
sleep 10

printf '==> Step 5: 检查 .env\n'
if [ ! -f .env ]; then
    printf 'ERROR: .env 不存在,请先 cp .env.example .env 并填入 token\n'
    exit 1
fi

printf '==> Step 6: 初始化数据库表\n'
python scripts/init_db.py

printf '==> 完成!可以开始数据加载: python scripts/full_load.py\n'
