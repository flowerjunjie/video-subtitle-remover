#!/bin/bash
# 海外本土剧承制 - 模型权重下载脚本
# 用法: bash download_models.sh
# 需要: huggingface-cli 登录 (huggingface-cli login)

set -e

WORKSPACE="$(cd "$(dirname "$0")" && pwd)"
MODELS_DIR="$WORKSPACE/models"

echo "=============================================="
echo " 海外本土剧承制 - 模型权重下载"
echo "=============================================="
echo ""

# 检查 huggingface-cli
if ! command -v huggingface-cli &> /dev/null; then
    echo "[ERROR] huggingface-cli 未安装"
    echo "安装: pip install huggingface_hub[cli]"
    exit 1
fi

# 登录检查
echo "[1/5] 检查 HuggingFace 登录状态..."
huggingface-cli whoami &> /dev/null && echo "  ✅ 已登录" || echo "  ⚠️ 未登录（公开模型可跳过）"

# ---- LongCat-Video-Avatar-1.5 (最大，约 50GB) ----
echo ""
echo "[2/5] 下载 LongCat-Video-Avatar-1.5 (~50GB)..."
LONGCAT_AVATAR_DIR="$MODELS_DIR/LongCat-Video_src/weights/LongCat-Video-Avatar-1.5"
if [ -d "$LONGCAT_AVATAR_DIR" ] && [ -n "$(ls -A "$LONGCAT_AVATAR_DIR" 2>/dev/null)" ]; then
    echo "  ✅ 已存在，跳过"
else
    mkdir -p "$(dirname "$LONGCAT_AVATAR_DIR")"
    huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.5 \
        --local-dir "$LONGCAT_AVATAR_DIR"
fi

# ---- MOSS-TTS-v1.5 (约 16GB) ----
echo ""
echo "[3/5] 下载 MOSS-TTS-v1.5 (~16GB)..."
MOSS_DIR="$MODELS_DIR/MOSS-TTS_src/weights/MOSS-TTS-v1.5"
if [ -d "$MOSS_DIR" ] && [ -n "$(ls -A "$MOSS_DIR" 2>/dev/null)" ]; then
    echo "  ✅ 已存在，跳过"
else
    mkdir -p "$(dirname "$MOSS_DIR")"
    huggingface-cli download OpenMOSS-Team/MOSS-TTS-v1.5 \
        --local-dir "$MOSS_DIR"
fi

# ---- MOSS-TTS-Nano ONNX (自动下载，无需手动) ----
echo ""
echo "[4/5] MOSS-TTS-Nano ONNX 模型..."
echo "  ℹ️ 首次运行自动从 HuggingFace 下载（~200MB），无需手动操作"

# ---- DeepLiveCam inswapper ----
echo ""
echo "[5/5] 检查 DeepLiveCam inswapper..."
INSWAPPER_PATH="$MODELS_DIR/DeepLiveCam_src/models/inswapper_128_fp16.onnx"
if [ -f "$INSWAPPER_PATH" ]; then
    echo "  ✅ 已存在"
else
    echo "  ⚠️ 未找到，从公开源下载..."
    mkdir -p "$(dirname "$INSWAPPER_PATH")"
    huggingface-cli download ambivalent/goon/inswapper_128_fp16.onnx \
        --local-dir "$MODELS_DIR/DeepLiveCam_src/models" \
        --local-dir-use-symlinks False
fi

echo ""
echo "=============================================="
echo " 下载完成!"
echo "=============================================="
echo ""
echo "下一步:"
echo "  1. pip install -r models/LongCat-Video_src/requirements_avatar.txt"
echo "  2. python app.py"
echo ""
