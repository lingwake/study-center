#!/usr/bin/env bash
# ============================================
#  学习中心 —— 一键启动(Windows 用 start.bat)
#  双击本文件即可启动服务,平板随即可以访问
# ============================================
cd "$(dirname "$0")"

echo "正在检查 Python..."
if ! command -v python3 >/dev/null 2>&1; then
  if ! command -v python >/dev/null 2>&1; then
    echo "❌ 没有检测到 Python,请先安装: https://www.python.org/downloads/"
    read -p "按回车退出..."
    exit 1
  fi
  PY=python
else
  PY=python3
fi

echo "正在启动服务..."
$PY server.py --port 8000

read -p "按回车退出..."
