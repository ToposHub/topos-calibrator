#!/bin/bash

# ███████╗████████╗███████╗██╗░░░░░██╗░░░░░
# ██╔════╝╚══██╔══╝██╔════╝██║░░░░░██║░░░░░
# █████╗░░░░░██║░░░█████╗░░██║░░░░░██║░░░░░
# ██╔══╝░░░░░██║░░░██╔══╝░░██║░░░░░██║░░░░░
# ██║░░░░░░░░██║░░░███████╗███████╗███████╗
# ╚═╝░░░░░░░░╚═╝░░░╚══════╝╚══════╝╚══════╝
# Topos Calibrator - 显示器校正与测量软件

echo "🚀 正在启动 Topos Calibrator..."
echo "────────────────────────────────────────"

# 1. 进入脚本所在目录
cd "$(dirname "$0")" || exit

# 2. 加载 Zsh 环境变量
if [ -f "$HOME/.zshrc" ]; then
  source "$HOME/.zshrc"
fi

# 3. 检测 Python 命令 (macOS 优先使用 python3)
if [ -d ".venv" ]; then
  echo "📦 找到 .venv，激活虚拟环境..."
  source .venv/bin/activate
  PYTHON_CMD="python"
else
  echo "⚠️  未找到 .venv，使用系统 Python..."
  # macOS 优先用 python3，否则用 python
  if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
  elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
  else
    echo "❌ 未找到 Python，请安装 Python"
    exit 1
  fi
fi

# 4. 运行主程序
echo "🎮 启动 Topos Calibrator..."
echo "────────────────────────────────────────"
$PYTHON_CMD main.py

# 5. 保持窗口打开
echo ""
echo "ℹ️  程序已退出。按回车键关闭窗口..."
read

