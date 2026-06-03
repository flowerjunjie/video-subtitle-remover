# 海外本土剧承制 · LongCat-Video-Avatar 解决方案

## 一、方案概述

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  🎬 海外本土剧承制 · 技术方案 (基于 LongCat-Video-Avatar)                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│  输入：中文原片(mov/mp4) + 英文字幕(srt)                                        │
│  输出：欧美演员视频 + 英文配音 + 英文字幕                                        │
│                                                                                 │
│  核心技术栈：                                                                   │
│  ① MOSS-TTS (8B) — 英文明星配音生成                                             │
│  ② LongCat-Video-Avatar-1.5 — Whisper-Large口型同步 + 视频生成                   │
│  ③ FFmpeg — 音频处理 + 字幕压制                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 二、Pipeline 架构

```
输入视频 + 英文字幕
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: 音频分离                                                │
│  ffmmpeg -i video → 原始音轨(WAV 48kHz)                           │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: TTS配音生成                                             │
│  MOSS-TTS-v1.5 (8B)                                              │
│  ├── 方式A: 参考原音克隆 — 保留原演员音色，生成英文配音           │
│  └── 方式B: 直接合成 — 用欧美声优参考音频，生成全新配音            │
│  输出: 英文配音WAV                                               │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: LongCat-Video-Avatar-1.5 生成视频                       │
│  ├── 参考图: 欧美脸(高清正脸) 或 从视频抽帧                       │
│  ├── 音频: 英文配音WAV                                           │
│  ├── 模型: avatar-v1.5 (Whisper-Large-v3 音频编码器)               │
│  ├── 加速: --use_distill (8步推理) + --use_int8                   │
│  └── 分辨率: 720P (可选480P)                                      │
│  输出: 欧美演员说话视频(无字幕)                                    │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: 字幕压制                                                │
│  ffmpeg -i avatar_video + srt → 最终成片                          │
└─────────────────────────────────────────────────────────────────┘
```

## 三、核心模块详解

### 3.1 音频分离

```python
def extract_audio(video_path: str, output_wav: str) -> str:
    """从视频提取48kHz立体声WAV"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",  # 不要视频
        "-acodec", "pcm_s16le",
        "-ar", "48000",
        "-ac", "2",
        output_wav
    ]
    subprocess.run(cmd, capture_output=True)
    return output_wav
```

### 3.2 MOSS-TTS 配音生成

```python
# 方式A: 声音克隆（保留原演员音色）
def generate_tts_clone(reference_audio: str, text: str, output: str) -> str:
    """用原音克隆生成英文配音"""
    from transformers import AutoModel, AutoProcessor
    import torch

    model = AutoModel.from_pretrained(
        "OpenMOSS-Team/MOSS-TTS-v1.5",
        trust_remote_code=True
    ).cuda()
    processor = model

    messages = [processor.build_user_message(
        text=text,
        reference=[reference_audio],  # 原音作为参考
        language="en"
    )]

    with torch.no_grad():
        outputs = model.generate(
            input_ids=processor(messages, mode="generation")["input_ids"].cuda(),
            max_new_tokens=4096
        )

    audio = processor.decode(outputs)[0].audio_codes_list[0]
    torchaudio.save(output, audio.unsqueeze(0), 48000)
    return output

# 方式B: 直接合成（欧美声优）
def generate_tts_direct(voice_description: str, text: str, output: str) -> str:
    """用VoxCPM直接描述声音特征生成"""
    # VoxCPM 支持直接用文本描述声音："young female, American accent, warm tone"
    pass
```

### 3.3 LongCat-Video-Avatar-1.5 推理

```bash
# 基础命令
torchrun --nproc_per_node=2 run_demo_avatar_single_audio_to_video.py \
  --context_parallel_size=2 \
  --checkpoint_dir=./weights/LongCat-Video-Avatar-1.5 \
  --stage_1=at2v \
  --input_json=assets/avatar/single_example_1.json \
  --use_distill \
  --model_type avatar-v1.5 \
  --use_int8 \
  --resolution 720

# 参数说明
# --stage_1=at2v         # Audio-Text-to-Video（音频驱动视频）
# --use_distill          # 蒸馏模式，8步推理（加速3倍）
# --use_int8             # INT8量化，降低显存
# --resolution 720       # 720P输出（可选480P）
# --num_segments=5       # 长视频分段数
# --audio_guidance_scale # 口型同步精度（默认3-5）
```

### 3.4 输入JSON格式

```json
// single_example_1.json
{
    "prompt": "A western man stands on stage under dramatic lighting, holding a microphone close to their mouth. Wearing a vibrant red jacket with gold embroidery, the singer is speaking while smoke swirls around them, creating a dynamic and atmospheric scene.",
    "cond_image": "assets/avatar/single/man.png",
    "cond_audio": {
        "person1": "assets/avatar/single/man.mp3"
    }
}
```

## 四、部署架构

```
┌─────────────────────────────────────────────────────────────────┐
│  px-cloud2 服务器 (NVIDIA A100 40GB)                            │
│                                                                 │
│  /workspace/overseas-drama-pipeline/                             │
│  ├── models/                                                     │
│  │   ├── LongCat-Video/           # LongCat-Video代码           │
│  │   │   ├── longcat_video/       # 核心模块                      │
│  │   │   ├── weights/             # 模型权重                       │
│  │   │   │   ├── LongCat-Video-Avatar-1.5/                        │
│  │   │   │   └── LongCat-Video-Avatar/                            │
│  │   │   ├── run_demo_avatar_single_audio_to_video.py             │
│  │   │   └── requirements_avatar.txt                               │
│  │   ├── MOSS-TTS_src/             # MOSS-TTS代码                 │
│  │   └── VoxCPM_src/               # VoxCPM代码                   │
│  ├── app.py                     # 主应用（Gradio UI）            │
│  ├── outputs/                    # 输出目录                       │
│  └── uploads/                    # 上传目录                       │
└─────────────────────────────────────────────────────────────────┘
```

## 五、环境依赖

```bash
# Python 3.10+ 环境
conda create -n longcat-video python=3.10
conda activate longcat-video

# PyTorch (CUDA 12.4)
pip install torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124

# FlashAttention-2
pip install ninja psutil packaging
pip install flash_attn==2.7.4.post1

# LongCat-Video Avatar 完整依赖
pip install -r requirements.txt
conda install -c conda-forge librosa ffmpeg
pip install -r requirements_avatar.txt

# MOSS-TTS 依赖
pip install transformers torch torchaudio

# MOSS-TTS-Nano ONNX CPU 运行时（首次自动下载模型，约 200MB）
pip install sentencepiece huggingface_hub onnxruntime

# LongCat-Avatar 运行时依赖（GPU 服务器必需）
pip install librosa audio-separator einops imageio pyloudnorm
# 或一键安装：
pip install -r models/LongCat-Video_src/requirements_avatar.txt
```

> **MOSS-TTS-Nano CPU Fallback**: 即使没有 GPU，MOSS-TTS-Nano (0.1B ONNX) 也可生成英文配音——首次运行自动从 HuggingFace 下载模型，无需手动下载。

## 六、模型下载

```bash
# 安装 huggingface-cli
pip install "huggingface_hub[cli]"

# 下载 LongCat-Video-Avatar-1.5 (推荐)
huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.5 --local-dir ./weights/LongCat-Video-Avatar-1.5

# 下载 MOSS-TTS-v1.5
huggingface-cli download OpenMOSS-Team/MOSS-TTS-v1.5 --local-dir ./weights/MOSS-TTS-v1.5

# 下载 VoxCPM (可选)
huggingface-cli download openbmb/VoxCPM2 --local-dir ./weights/VoxCPM2
```

## 七、性能与限制

```
┌─────────────────────────────────────────────────────────────────┐
│  硬件需求                                                       │
│  ├── GPU: NVIDIA A100 40GB (单卡可跑)                           │
│  ├── 显存: 720P + distill + int8 ≈ 20GB                        │
│  ├── 内存: 64GB+                                                 │
│  └── 磁盘: 200GB+ (模型+临时文件)                               │
├─────────────────────────────────────────────────────────────────┤
│  推理速度 (A100 40GB)                                           │
│  ├── Avatar-1.5 + distill + int8: ~8步/片段 ≈ 2-3分钟/片段      │
│  ├── Avatar-1.5 原生: 25步 ≈ 10分钟/片段                        │
│  └── 长视频: 多个片段拼接                                       │
├─────────────────────────────────────────────────────────────────┤
│  当前限制                                                       │
│  ├── 场景: 全合成，非原片换脸（需要接受风格差异）                 │
│  ├── 角色一致性: 多片段时需保证参考图一致                         │
│  ├── 口型精度: Whisper-Large v3 相比 Wav2Vec2 显著提升           │
│  └── 视频时长: 受GPU显存限制，需分段生成后拼接                   │
└─────────────────────────────────────────────────────────────────┘
```

## 八、执行计划

```
Phase 1: 环境部署 (预计2小时)
  ☐ 安装 conda 环境
  ☐ 安装 PyTorch + CUDA
  ☐ 安装 LongCat-Video 依赖
  ☐ 下载模型权重 (~50GB)
  ☐ 下载 MOSS-TTS 权重 (~16GB)

Phase 2: 单测验证 (预计1小时)
  ☐ LongCat-Video-Avatar 单片段推理测试
  ☐ MOSS-TTS 配音生成测试
  ☐ 端到端: 视频→配音→Avatar→字幕

Phase 3: 集成到 app.py (预计2小时)
  ☐ 新增 longcat_avatar_mode 选项
  ☐ Gradio UI 增加模式切换
  ☐ Pipeline 串联调试

Phase 4: 生产验证 (预计持续)
  ☐ 不同场景测试
  ☐ 性能优化
  ☐ 质量验收
```

## 九、关键风险

```
⚠️ 风险1: 显存不足
  720P + int8 + distill: ~20GB (A100 40GB 可跑)
  1080P: 需要多卡或更高显存

⚠️ 风险2: 生成式 vs 替换式
  LongCat-Video-Avatar 是全生成式，不是 DeepLiveCam 的换脸
  人物动作/表情/场景都是AI生成，非原片替换
  需要确认制作方接受这种风格

⚠️ 风险3: 角色一致性
  长视频多片段生成时，角色外观可能漂移
  需要固定参考图 + 短片段拼接

⚠️ 风险4: 口型精度
  虽然 Whisper-Large 比 Wav2Vec2 强，但仍有误差
  特别是在语速快/多音字情况下
```

## 十、替代方案（如果 Avatar 不可用）

```
方案B: DeepLiveCam 换脸 + Wav2Lip 口型同步
├── DeepLiveCam: inswapper 换欧美脸
├── Wav2Lip: 口型与配音同步
└── MOSS-TTS: 英文配音生成

优点: 原片动作保留，换脸真实
缺点: 口型精度较低，角色一致性差
```