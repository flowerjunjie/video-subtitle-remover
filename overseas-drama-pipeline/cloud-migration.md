# 云服务器迁移清单

## 当前环境

- 服务器：64.90.20.46（CPU only）
- 项目路径：`/workspace/overseas-drama-pipeline`
- 服务端口：7860
- 配置文件：`/workspace/overseas-drama-pipeline/config.json`

## GPU 服务器迁移步骤

### 1. 环境准备

```bash
# 1.1 创建项目目录
mkdir -p /workspace/overseas-drama-pipeline

# 1.2 安装 Python 3.10+
python3 --version  # 需要 >= 3.10

# 1.3 安装系统依赖
apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1-mesa-glx  # OpenCV 需要

# 1.4 安装 uv 包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. GPU 环境（根据显卡选择）

**NVIDIA CUDA：**
```bash
# 安装 CUDA 11.8 或 12.6
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-keyring_1.0-1_all.deb
dpkg -i cuda-keyring_1.0-1_all.deb
apt-get update
apt-get install -y cuda-runtime-11-8  # 或 cuda-runtime-12-6

# 验证
nvidia-smi
```

**AMD ROCm：**
```bash
apt-get install -y rocm-runtime
rocm-smi
```

### 3. 代码部署

```bash
# 方式A：Git 拉取
git clone <your-repo> /workspace/overseas-drama-pipeline

# 方式B：SCP 传输
scp -r ./overseas-drama-pipeline root@<new-server>:/workspace/
```

### 4. 依赖安装

```bash
cd /workspace/overseas-drama-pipeline

# 使用 uv 安装（推荐）
uv sync

# 或 pip 安装
pip install -r requirements.txt
```

**GPU 版本额外依赖：**
```bash
# NVIDIA
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# AMD
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm5.4

# DeepFaceLab / Wav2Lip
pip install deepfacelab  # GPU 版
```

### 5. 配置

```bash
# 复制配置文件（包含 API Key）
# 手动在 Web UI 中重新填写，或安全传输 config.json

# 创建必要的目录
mkdir -p /workspace/overseas-drama-pipeline/{uploads,outputs,models}
```

### 6. 服务启动

```bash
# 启动服务
cd /workspace/overseas-drama-pipeline
nohup python3 app.py > /var/log/overseas-drama.log 2>&1 &

# 验证启动
ss -tlnp | grep 7860
curl http://localhost:7860
```

### 7. 进程守护（systemd）

```bash
# 创建服务文件
cat > /etc/systemd/system/overseas-drama.service << EOF
[Unit]
Description=Overseas Drama Pipeline
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/workspace/overseas-drama-pipeline
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 启用服务
systemctl daemon-reload
systemctl enable overseas-drama
systemctl start overseas-drama

# 检查状态
systemctl status overseas-drama
```

### 8. Nginx 反向代理（可选）

```bash
cat > /etc/nginx/sites-available/overseas-drama << EOF
server {
    listen 8090;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 300;
    }
}
EOF

ln -s /etc/nginx/sites-available/overseas-drama /etc/nginx/sites-enabled/
nginx -t && nginx -s reload
```

## 验证清单

```bash
# 启动后执行以下验证

# 1. 服务健康检查
curl http://localhost:7860/ | head -5

# 2. GPU 检测（GPU 服务器）
python3 -c "import torch; print(f'CUDA: {torch.cuda.is_available()}')"

# 3. Whisper 模型下载
python3 -c "import whisper; print('Whisper OK')"

# 4. FFmpeg
ffmpeg -version | head -1

# 5. 进程守护
systemctl status overseas-drama
```

## 常见问题

### 问题1：ImportError: No module named 'cv2'
```bash
pip install opencv-python-headless  # 无头版本，更轻量
```

### 问题2：GPU 显存不足
```bash
# 减小 batch size
export CUDA_VISIBLE_DEVICES=0
python3 app.py  # 单 GPU
```

### 问题3：端口被占用
```bash
fuser -k 7860/tcp
python3 app.py --port 7861  # 换端口
```

## 快速启动脚本

创建 `deploy.sh`：
```bash
#!/bin/bash
set -e

echo "=== 部署海外剧本地化流水线 ==="

# 1. 依赖安装
echo "[1/5] 安装依赖..."
pip install -r requirements.txt

# 2. 目录创建
echo "[2/5] 创建目录..."
mkdir -p uploads outputs models

# 3. 服务停止
echo "[3/5] 停止旧服务..."
pkill -f "python3 app.py" || true

# 4. 服务启动
echo "[4/5] 启动服务..."
nohup python3 app.py > /var/log/overseas-drama.log 2>&1 &

# 5. 验证
echo "[5/5] 验证服务..."
sleep 3
if curl -s http://localhost:7860 > /dev/null; then
    echo "✅ 服务启动成功: http://localhost:7860"
else
    echo "❌ 服务启动失败，查看日志: /var/log/overseas-drama.log"
    exit 1
fi
```

## 目录结构

```
/workspace/overseas-drama-pipeline/
├── app.py              # 主程序
├── requirements.txt    # 依赖
├── config.json        # API配置（手动填写）
├── cloud-migration.md  # 本文档
├── uploads/           # 上传文件
├── outputs/           # 输出文件
├── models/            # Whisper 模型缓存
└── logs/              # 日志目录
```
