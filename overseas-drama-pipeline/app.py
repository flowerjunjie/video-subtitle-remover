"""
海外本土剧承制 - 全链路本地化 Demo
Gradio UI - 支持视频上传 + 换脸 + 口型同步 + 配音 + 字幕翻译
"""

import os
import re
import shlex
import subprocess
import shutil
import json
import threading
import uuid
import tempfile
from pathlib import Path
from datetime import datetime

import gradio as gr
import whisper
from gtts import gTTS

# ============== 配置 ==============
WORKSPACE = "/workspace/overseas-drama-pipeline"
UPLOAD_DIR = os.path.join(WORKSPACE, "uploads")
OUTPUT_DIR = os.path.join(WORKSPACE, "outputs")
MODEL_DIR = os.path.join(WORKSPACE, "models")
CONFIG_FILE = os.path.join(WORKSPACE, "config.json")
MAX_FILE_SIZE_MB = 500

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

# ============== Whisper 模型缓存（避免重复加载）=============
_loaded_models = {}

# ============== 取消事件 ==============
_cancel_event = threading.Event()

def is_cancelled():
    return _cancel_event.is_set()

def cancel_processing():
    _cancel_event.set()

def get_whisper_model(model_size: str = "base", progress=None):
    """加载 Whisper 模型并缓存，避免每次重新加载"""
    if model_size not in _loaded_models:
        if progress is not None:
            progress(0, desc=f"加载 Whisper {model_size} 模型中...")
        _loaded_models[model_size] = whisper.load_model(model_size, download_root=MODEL_DIR)
    return _loaded_models[model_size]

# ============== 配置文件管理 ==============

def load_config() -> dict:
    """加载配置，优先使用环境变量中的 Key"""
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            config = {}

    # 环境变量覆盖配置文件（生产环境推荐）
    if os.environ.get("OPENAI_API_KEY"):
        config["openai_api_key"] = os.environ.get("OPENAI_API_KEY")
    if os.environ.get("DEEPSEEK_API_KEY"):
        config["deepseek_api_key"] = os.environ.get("DEEPSEEK_API_KEY")
    if os.environ.get("ELEVENLABS_API_KEY"):
        config["elevenlabs_api_key"] = os.environ.get("ELEVENLABS_API_KEY")
    if os.environ.get("ELEVENLABS_VOICE_ID"):
        config["elevenlabs_voice_id"] = os.environ.get("ELEVENLABS_VOICE_ID")

    # 确保默认字段存在（用 or "" 处理 explicit null 值）
    config["openai_api_key"] = config.get("openai_api_key") or ""
    config["deepseek_api_key"] = config.get("deepseek_api_key") or ""
    config["elevenlabs_api_key"] = config.get("elevenlabs_api_key") or ""
    config["elevenlabs_voice_id"] = config.get("elevenlabs_voice_id") or ""
    config["translation_model"] = config.get("translation_model") or "gpt-4o"
    config["tts_provider"] = config.get("tts_provider") or "edge"

    return config

def save_config(config: dict):
    """保存配置"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        os.chmod(CONFIG_FILE, 0o600)  # 限制配置文件权限，防止 API Key 泄露
    except Exception as e:
        raise Exception(f"配置保存失败: {e}")

# ============== 工具函数 ==============

def extract_audio(video_path: str, audio_path: str = None) -> str:
    """从视频提取音频"""
    if audio_path is None:
        audio_path = video_path.replace(".mp4", "_audio.wav").replace(".mov", "_audio.wav")
    os.makedirs(os.path.dirname(audio_path) or ".", exist_ok=True)
    cmd = f'ffmpeg -y -i {shlex.quote(video_path)} -vn -acodec pcm_s16le -ar 16000 -ac 1 {shlex.quote(audio_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr
        if isinstance(err, bytes):
            err = err.decode(errors='replace')
        raise Exception(f"ffmpeg 音频提取失败: {err or '未知错误'}")
    return audio_path

def transcribe_audio(audio_path: str, model_size: str = "base", progress=None) -> dict:
    """Whisper 语音识别"""
    model = get_whisper_model(model_size, progress)
    if progress is not None:
        progress(0.2, desc="Whisper 模型已加载，开始识别...")
    result = model.transcribe(audio_path, language="zh")
    # 防御：如果 Whisper 返回空结果（静音/无法识别音频）
    if not result.get("text", "").strip():
        raise ValueError(f"Whisper 语音识别返回空结果: {audio_path}")
    return result

def translate_to_english_openai(text: str, api_key: str) -> str:
    """使用 OpenAI GPT 翻译"""
    if not api_key:
        raise ValueError("OpenAI API Key 未配置")
    if not text or not text.strip():
        raise ValueError("翻译文本为空")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional subtitle translator. Translate Chinese subtitles to English.
Rules:
- Keep it natural and conversational
- Use appropriate Western names for characters if they are Chinese
- Maintain the tone and style of the original
- Return ONLY the translated text, no explanations"""
                },
                {
                    "role": "user",
                    "content": f"Translate: {text}"
                }
            ],
            max_tokens=2000,
            temperature=0.3
        )
        raw = response.choices[0].message.content
        if not raw:
            raise RuntimeError("OpenAI/DeepSeek API returned empty translation")
        return raw.strip()
    except Exception as e:
        error_msg = str(e)
        if "Incorrect API key" in error_msg or "invalid_api_key" in error_msg:
            raise ValueError(f"OpenAI API Key 无效: {error_msg}")
        elif "Rate limit" in error_msg or "429" in error_msg:
            raise RuntimeError(f"OpenAI 请求频率超限: {error_msg}")
        elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
            raise ConnectionError(f"OpenAI API 连接失败: {error_msg}")
        else:
            raise RuntimeError(f"翻译失败: {error_msg}")

def translate_to_english_deepseek(text: str, api_key: str, model: str = "deepseek-chat") -> str:
    """使用 DeepSeek 翻译"""
    if not api_key:
        raise ValueError("DeepSeek API Key 未配置")
    if not text or not text.strip():
        raise ValueError("翻译文本为空")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional subtitle translator. Translate Chinese subtitles to English.
Rules:
- Keep it natural and conversational
- Use appropriate Western names for characters if they are Chinese
- Maintain the tone and style of the original
- Return ONLY the translated text, no explanations"""
                },
                {
                    "role": "user",
                    "content": f"Translate: {text}"
                }
            ],
            max_tokens=2000,
            temperature=0.3
        )
        raw = response.choices[0].message.content
        if not raw:
            raise RuntimeError("OpenAI/DeepSeek API returned empty translation")
        return raw.strip()
    except Exception as e:
        error_msg = str(e)
        if "Incorrect API key" in error_msg or "invalid_api_key" in error_msg or "api_key" in error_msg.lower():
            raise ValueError(f"DeepSeek API Key 无效: {error_msg}")
        elif "Rate limit" in error_msg or "429" in error_msg:
            raise RuntimeError(f"DeepSeek 请求频率超限: {error_msg}")
        elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
            raise ConnectionError(f"DeepSeek API 连接失败: {error_msg}")
        else:
            raise RuntimeError(f"翻译失败: {error_msg}")

def format_srt_time(seconds: float) -> str:
    """将秒数转换为 SRT 时间格式 HH:MM:SS,mmm"""
    # 防御：负数时间在 SRT 中无意义，截断为 0
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def generate_srt_from_segments(segments: list, english_lines: list) -> str:
    """根据 Whisper segments 生成真实 SRT 字幕"""
    srt_lines = []
    for i, (seg, en_text) in enumerate(zip(segments, english_lines), 1):
        start = seg.get("start", 0)
        end = seg.get("end", start + 1)  # 保证 end >= start，防止零时长字幕
        if end <= start:
            end = start + 1
        srt_lines.append(f"{i}")
        srt_lines.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
        srt_lines.append(en_text if en_text else "")
        srt_lines.append("")
    return "\n".join(srt_lines)

def burn_subtitle_ffmpeg(video_path: str, srt_path: str, output_path: str = None) -> str:
    """
    使用 FFmpeg 将 SRT 字幕烧入视频
    返回烧录后的视频路径，失败时返回原视频路径
    """
    if not srt_path or not os.path.isfile(srt_path):
        return video_path
    if not output_path:
        output_path = video_path
    try:
        # 使用 FFmpeg subtitles 滤镜烧录 SRT
        cmd = f'ffmpeg -y -i {shlex.quote(video_path)} -vf subtitles={shlex.quote(srt_path)} -c:a copy {shlex.quote(output_path)}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            err = result.stderr
            if isinstance(err, bytes):
                err = err.decode(errors='replace')
            print(f"[字幕烧录失败: {err}]")
            return video_path
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            print(f"[字幕烧录后文件为空]")
            return video_path
        return output_path
    except Exception as e:
        print(f"[字幕烧录异常: {e}]")
        return video_path

def generate_tts_gtts(text: str, output_path: str) -> str:
    """生成 TTS 音频 (gTTS) - 仅作为 edge-tts 的备用方案"""
    if not text or not text.strip():
        raise ValueError("TTS text is empty")
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(output_path)
        return output_path
    except Exception as e:
        print(f"[gTTS failed: {e}, switching to edge-tts]")
        return generate_tts_edge(text, output_path)

def run_wav2lip(face_video: str, audio: str, output_path: str, target_face: str = None) -> str:
    """运行 Wav2Lip 口型同步"""
    import sys
    sys.path.insert(0, os.path.join(MODEL_DIR, "Wav2Lip"))
    from models import Wav2Lip
    import face_detection
    import torch
    import audio as wav2lip_audio
    import cv2
    import numpy as np
    from tqdm import tqdm
    from hparams import hparams as hp

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    checkpoint_path = os.path.join(MODEL_DIR, "Wav2Lip", "checkpoints", "wav2lip.pth")

    if not os.path.exists(checkpoint_path):
        raise FileNotFoundError(f"Wav2Lip model not found: {checkpoint_path}")

    print(f"[Wav2Lip] Loading model...")
    model = Wav2Lip().to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)

    # 处理三种 checkpoint 格式
    state_dict = None
    if 'model' in checkpoint:
        state_dict = checkpoint['model']
    elif 'state_dict' in checkpoint:
        state_dict = checkpoint['state_dict']
    else:
        state_dict = checkpoint

    # 去掉 "module." 前缀（DataParallel 训练产生的）
    new_state_dict = {}
    for k, v in state_dict.items():
        if k.startswith('module.'):
            new_state_dict[k[7:]] = v
        else:
            new_state_dict[k] = v

    model.load_state_dict(new_state_dict, strict=False)  # strict=False容忍缺失key（如loss相关）
    model.eval()

# 提取音频 - 使用本地 extract_audio (基于 ffmpeg)
    audio_path = os.path.join(OUTPUT_DIR, "temp_audio.wav")
    cmd = f'ffmpeg -y -i {shlex.quote(face_video)} -vn -acodec pcm_s16le -ar 16000 -ac 1 {shlex.quote(audio_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        err_msg = result.stderr
        if isinstance(err_msg, bytes):
            err_msg = err_msg.decode(errors='replace')
        raise Exception(f"Wav2Lip 音频提取失败: {err_msg or '未知错误'}")

    # 读取视频
    video_cap = cv2.VideoCapture(face_video)
    fps = video_cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 25.0  # 防御：fps读取失败时默认25
    frames = []
    while True:
        ret, frame = video_cap.read()
        if not ret:
            break
        frames.append(frame)
    video_cap.release()
    print(f"[Wav2Lip] {len(frames)} frames at {fps:.1f} fps")
    if len(frames) == 0:
        raise ValueError(f"Wav2Lip 视频为空或无法读取: {face_video}")

    # 人脸检测
    detector = face_detection.FaceAlignment(
        face_detection.LandmarksType._2D, flip_input=False, device=device
    )
    face_det_results = []
    pady1, pady2, padx1, padx2 = 0, 10, 0, 0

    for frame in tqdm(frames, desc="[Wav2Lip] Detecting faces"):
        dets = detector.get_detections_for_batch(np.array([frame]))
        # 防御：dets 为空列表时避免 IndexError
        if dets and dets[0] is not None:
            rect = dets[0]
            y1 = max(0, rect[1] - pady1)
            y2 = min(frame.shape[0], rect[3] + pady2)
            x1 = max(0, rect[0] - padx1)
            x2 = min(frame.shape[1], rect[2] + padx2)
            face_det_results.append([x1, y1, x2, y2])
        else:
            face_det_results.append([0, 0, frame.shape[1], frame.shape[0]])

    # 处理 mel spectrogram - 使用正确的 melspectrogram 函数
    wav = wav2lip_audio.load_wav(audio_path, hp.sample_rate)
    mel = wav2lip_audio.melspectrogram(wav)
    mel = mel.astype(np.float32)
    mel_idx = 0

    print(f"[Wav2Lip] Processing {len(frames)} frames...")
    processed_frames = []
    batch_size = 128

    for i in tqdm(range(0, len(frames), batch_size), desc="[Wav2Lip] Processing"):
        batch_frames = frames[i:i+batch_size]
        batch_boxes = face_det_results[i:i+batch_size]

        for j, (frame, box) in enumerate(zip(batch_frames, batch_boxes)):
            x1, y1, x2, y2 = box
            face = frame[y1:y2, x1:x2]
            if face.size == 0:
                processed_frames.append(frame)
                continue

            face_resized = cv2.resize(face, (96, 96)).astype(np.float32) / 255.0
            # Wav2Lip expects 6 channels: upper half zeroed + full face (axis=2 for HWC)
            face_masked = face_resized.copy()
            face_masked[:48, :, :] = 0  # zero upper half
            face_combined = np.concatenate([face_masked, face_resized], axis=2)  # [96, 96, 6]
            face_tensor = torch.FloatTensor(face_combined).permute(2, 0, 1).unsqueeze(0).to(device)

            # 获取对应 mel 段 (shape: [1, 1, 80, 16])
            mel_idx = min(mel_idx, mel.shape[1] - 16)
            mel_idx = max(0, mel_idx)  # 防御：防止负索引
            mel_chunk = torch.FloatTensor(mel[:, mel_idx:mel_idx+16]).unsqueeze(0).unsqueeze(0).to(device)
            mel_idx += 1

            with torch.no_grad():
                pred = model(mel_chunk, face_tensor)
                pred = pred.squeeze().cpu().numpy().transpose(1, 2, 0)
                pred = (pred * 255).clip(0, 255).astype(np.uint8)

            pred = cv2.resize(pred, (x2 - x1, y2 - y1))
            result = frame.copy()
            result[y1:y2, x1:x2] = pred
            processed_frames.append(result)

    # 写入视频
    height, width = processed_frames[0].shape[:2]
    temp_video = output_path.replace('.mp4', '_nosound.mp4')
    out = cv2.VideoWriter(temp_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
    for frame in processed_frames:
        out.write(frame)
    out.release()

    # 检查写入是否成功
    if not (os.path.exists(temp_video) and os.path.getsize(temp_video) > 0):
        raise RuntimeError(f"Wav2Lip 视频写入失败（文件为空）: {temp_video}")

    # 合并音频 - 必须用 TTS 音频 (audio 参数)，不能用 audio_path（那是原视频音频）
    cmd = f'ffmpeg -y -i {shlex.quote(temp_video)} -i {shlex.quote(audio)} -map 0:v -map 1:a -c:v copy -c:a aac -shortest {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        err_msg = result.stderr
        if isinstance(err_msg, bytes):
            err_msg = err_msg.decode(errors='replace')
        print(f"[Wav2Lip] ffmpeg warning: {err_msg}")
    # 防御：ffmpeg 合成后检查输出文件完整性（returncode=0不代表文件完整）
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Wav2Lip 音频合并后输出文件为空: {output_path}")
    os.remove(temp_video)
    os.remove(audio_path)

    print(f"[Wav2Lip] Done: {output_path}")
    return output_path

def run_deep_live_cam(source_face: str, target_video: str, output_path: str) -> str:
    """运行 DeepLiveCam 换脸"""
    import sys
    deeplivecam_root = os.path.join(MODEL_DIR, "DeepLiveCam_src")
    sys.path.insert(0, deeplivecam_root)
    from modules.core import suggest_default_execution_provider, parse_args as dlc_parse_args
    import modules.globals
    import modules.metadata
    from modules.utilities import extract_frames, create_video, move_temp, get_temp_frame_paths

    modules.globals.source_path = source_face
    modules.globals.target_path = target_video
    modules.globals.output_path = output_path
    modules.globals.frame_processors = ['face_swapper']
    modules.globals.keep_fps = True
    modules.globals.keep_audio = False
    modules.globals.keep_frames = False
    modules.globals.many_faces = False
    modules.globals.execution_providers = [suggest_default_execution_provider()]
    modules.globals.execution_threads = 4  # 避免 max_workers=None
    modules.globals.log_level = "error"

    inswapper_model = os.path.join(MODEL_DIR, "DeepLiveCam_src", "models", "inswapper_128_fp16.onnx")
    if not os.path.exists(inswapper_model):
        raise FileNotFoundError(f"DeepLiveCam inswapper model not found: {inswapper_model}")

    # 创建 temp 目录（DeepLiveCam 需要）
    from modules.utilities import create_temp
    create_temp(modules.globals.target_path)

    # 提取帧 - extract_frames 内部只用 target_path
    extract_frames(modules.globals.target_path)

    # 处理每帧 - 使用 DeepLiveCam 的 face_swapper 模块
    from modules.processors.frame.core import multi_process_frame
    from modules.processors.frame.face_swapper import swap_face
    from modules.face_analyser import get_one_face
    import cv2
    import numpy as np

    source_img = cv2.imread(source_face)
    if source_img is None:
        raise Exception(f"无法读取源面孔图片: {source_face}")
    source_face_obj = get_one_face(source_img)
    if source_face_obj is None:
        raise Exception(f"源图片中未检测到人脸: {source_face}")

    frame_paths = get_temp_frame_paths(modules.globals.target_path)
    for frame_path in frame_paths:
        try:
            frame = cv2.imread(frame_path)
            if frame is None:
                continue
            target_faces = get_one_face(frame)
            if target_faces:
                swapped = swap_face(source_face_obj, target_faces, frame)
                cv2.imwrite(frame_path, swapped)
        except Exception as write_err:
            print(f"[DeepLiveCam] Frame write error ({frame_path}): {write_err}")
            continue

    # 初始化 video_quality 和 video_encoder（防止 None 导致编码器异常）
    if modules.globals.video_quality is None:
        modules.globals.video_quality = 23
    if modules.globals.video_encoder is None:
        modules.globals.video_encoder = 'libx264'
    if modules.globals.execution_threads is None:
        modules.globals.execution_threads = 4

    # 合成视频 - create_video 写入 temp 目录，需要手动 move_temp 到 output_path
    success = create_video(modules.globals.target_path, 30.0)
    if not success:
        raise Exception("DeepLiveCam 视频合成失败")
    move_temp(modules.globals.target_path, output_path)
    # 防御：验证输出文件存在且非空（move_temp 可能静默失败）
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"DeepLiveCam 输出文件为空或不存在: {output_path}")

    print(f"[DeepLiveCam] Done: {output_path}")
    return output_path

def run_longcat_avatar(
    cond_image_path: str,
    audio_path: str,
    output_path: str,
    prompt: str = "A western person speaking in a clear voice, with natural expressions.",
    model_type: str = "avatar-v1.5",
    resolution: int = 720,
    num_segments: int = 1,
    use_distill: bool = True,
    audio_guidance_scale: float = 3.0,
    negative_prompt: str = None,
) -> str:
    """运行 LongCat-Video-Avatar 视频生成（音频驱动全生成）

    Args:
        cond_image_path: 参考图路径（欧美脸高清正脸）
        audio_path: TTS 英文配音音频路径
        output_path: 输出视频路径
        prompt: 场景描述文本
        model_type: avatar-v1.5 或 avatar-v1.0
        resolution: 720 或 480
        num_segments: 长视频分段数（默认1为单片段）
        use_distill: 使用蒸馏8步推理（加速3倍）
        audio_guidance_scale: 口型同步精度（3-5最佳）
        negative_prompt: 负向提示词（默认使用内置默认值）

    Returns:
        生成的视频路径（含音轨）

    Raises:
        RuntimeError: 依赖缺失或无 GPU 时抛出
    """
    import sys
    import math
    import subprocess
    import numpy as np
    import PIL.Image
    import librosa
    import torch

    # 前置依赖检查（GPU + 必需包）
    for pkg, install_cmd in [
        ("librosa", "pip install librosa"),
        ("audio_separator", "pip install audio-separator"),
        ("einops", "pip install einops"),
        ("imageio", "pip install imageio"),
        ("pyloudnorm", "pip install pyloudnorm"),
        ("flash_attn", "pip install flash_attn --no-build-isolation"),
    ]:
        try:
            __import__(pkg)
        except ImportError:
            raise RuntimeError(
                f"LongCat-Avatar 依赖缺失: {pkg}\n"
                f"安装命令: {install_cmd}\n"
                "或运行: cd models/LongCat-Video_src && pip install -r requirements_avatar.txt"
            )

    longcat_root = os.path.join(MODEL_DIR, "LongCat-Video_src")
    sys.path.insert(0, longcat_root)

    from longcat_video.pipeline_longcat_video_avatar import LongCatVideoAvatarPipeline
    from longcat_video.modules.scheduling_flow_match_euler_discrete import FlowMatchEulerDiscreteScheduler
    from longcat_video.modules.autoencoder_kl_wan import AutoencoderKLWan
    from longcat_video.modules.avatar.longcat_video_dit_avatar import LongCatVideoAvatarTransformer3DModel
    from longcat_video.audio_process import get_audio_encoder, get_audio_feature_extractor
    from longcat_video.audio_process.torch_utils import save_video_ffmpeg
    from audio_separator.separator import Separator
    from transformers import AutoTokenizer, UMT5EncoderModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device != "cuda":
        raise RuntimeError("LongCat-Video-Avatar 需要 CUDA GPU，当前环境无 GPU")

    checkpoint_dir = os.path.join(longcat_root, "weights", "LongCat-Video-Avatar-1.5")
    if not os.path.exists(checkpoint_dir):
        raise FileNotFoundError(
            f"LongCat-Video-Avatar 权重未找到: {checkpoint_dir}\n"
            "请先下载模型: huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.5 --local-dir ./weights/LongCat-Video-Avatar-1.5"
        )

    if resolution == 480:
        height, width = 480, 832
    elif resolution == 720:
        height, width = 768, 1280
    else:
        raise ValueError(f"resolution 必须是 480 或 720，当前: {resolution}")

    save_fps = 25
    audio_stride = 1
    num_frames = 93
    num_cond_frames = 13
    if negative_prompt is None:
        negative_prompt = (
            "Close-up, Bright tones, overexposed, static, blurred details, subtitles, "
            "style, works, paintings, images, static, overall gray, worst quality, "
            "low quality, JPEG compression residue, ugly, incomplete, extra fingers, "
            "poorly drawn hands, poorly drawn faces, deformed, disfigured, misshapen limbs, "
            "fused fingers, still picture, messy background, three legs, many people in the background"
        )

    print(f"[LongCat-Avatar] Loading models from {checkpoint_dir}...")

    tokenizer = AutoTokenizer.from_pretrained(
        os.path.join(longcat_root, "weights", "..", "LongCat-Video"),
        subfolder="tokenizer", torch_dtype=torch.bfloat16
    )
    text_encoder = UMT5EncoderModel.from_pretrained(
        os.path.join(longcat_root, "weights", "..", "LongCat-Video"),
        subfolder="text_encoder", torch_dtype=torch.bfloat16
    )
    vae = AutoencoderKLWan.from_pretrained(
        os.path.join(longcat_root, "weights", "..", "LongCat-Video"),
        subfolder="vae", torch_dtype=torch.bfloat16
    )
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
        checkpoint_dir, subfolder="scheduler", torch_dtype=torch.bfloat16
    )

    from longcat_video.modules.quantization import load_quantized_dit
    print("[LongCat-Avatar] Loading INT8 quantized DiT...")
    try:
        dit = load_quantized_dit(checkpoint_dir, subfolder="base_model_int8", cp_split_hw=None)
    except Exception as dit_err:
        raise RuntimeError(
            f"LongCat-Video DiT 加载失败 (可能是 GPU compute capability 不支持 bfloat16): {dit_err}\n"
            f"当前 GPU 可能不满足 LongCat-Avatar 最低要求（sm_75 及以上）"
        ) from dit_err

    if use_distill:
        distill_path = os.path.join(checkpoint_dir, "lora", "dmd_lora.safetensors")
        if os.path.exists(distill_path):
            dit.load_lora(distill_path, "dmd", multiplier=1.0, lora_network_dim=128, lora_network_alpha=64)
            dit.enable_loras(["dmd"])

    if model_type == "avatar-v1.5":
        audio_model_path = os.path.join(checkpoint_dir, "whisper-large-v3")
    else:
        audio_model_path = os.path.join(checkpoint_dir, "chinese-wav2vec2-base")

    audio_encoder = get_audio_encoder(audio_model_path, model_type).to(device)
    audio_feature_extractor = get_audio_feature_extractor(audio_model_path, model_type)

    pipe = LongCatVideoAvatarPipeline(
        tokenizer=tokenizer,
        text_encoder=text_encoder,
        vae=vae,
        scheduler=scheduler,
        dit=dit,
        audio_encoder=audio_encoder,
        audio_feature_extractor=audio_feature_extractor,
        model_type=model_type
    )
    pipe.to(device)

    print(f"[LongCat-Avatar] Processing audio: {audio_path}")
    vocal_separator_path = os.path.join(checkpoint_dir, "vocal_separator", "Kim_Vocal_2.onnx")
    audio_temp_dir = os.path.join(OUTPUT_DIR, "avatar_audio_temp")
    os.makedirs(audio_temp_dir, exist_ok=True)

    vocal_separator = Separator(
        output_dir=os.path.join(audio_temp_dir, "vocals"),
        output_single_stem="vocals",
        model_file_dir=os.path.dirname(vocal_separator_path),
    )
    try:
        vocal_separator.load_model(os.path.basename(vocal_separator_path))
    except Exception as load_err:
        raise RuntimeError(f"Audio separator 模型加载失败: {load_err}") from load_err

    temp_vocal_path = os.path.join(audio_temp_dir, f"vocal_{uuid.uuid4().hex[:8]}.wav")
    outputs = vocal_separator.separate(audio_path)
    if outputs:
        import shutil
        src = os.path.join(audio_temp_dir, "vocals", outputs[0])
        try:
            shutil.move(src, temp_vocal_path)
        except Exception as move_err:
            print(f"[LongCat-Avatar] Vocal file move failed ({move_err}), using original audio")
            temp_vocal_path = audio_path
    else:
        print("[LongCat-Avatar] Vocal separation failed, using original audio")
        temp_vocal_path = audio_path

    # 防御：若 temp_vocal_path 无效，回退到原始音频
    if not os.path.isfile(temp_vocal_path):
        print(f"[LongCat-Avatar] Vocal file missing ({temp_vocal_path}), using original audio")
        temp_vocal_path = audio_path

    generate_duration = num_frames / save_fps + (num_segments - 1) * (num_frames - num_cond_frames) / save_fps
    try:
        speech_array, sr = librosa.load(temp_vocal_path, sr=16000)
    except Exception as audio_load_err:
        raise RuntimeError(
            f"LongCat-Avatar 音频加载失败: {audio_load_err}\n"
            f"音频文件: {temp_vocal_path}，大小: {os.path.getsize(temp_vocal_path) if os.path.isfile(temp_vocal_path) else 'N/A'} bytes"
        ) from audio_load_err
    source_duration = len(speech_array) / sr
    added_samples = math.ceil((generate_duration - source_duration) * sr)
    if added_samples > 0:
        speech_array = np.append(speech_array, [0.0] * added_samples)

    print(f"[LongCat-Avatar] Computing audio embedding (fps={save_fps * audio_stride})...")
    full_audio_emb = pipe.get_audio_embedding(
        speech_array,
        fps=save_fps * audio_stride,
        device=device,
        sample_rate=sr,
        model_type=model_type
    )
    if torch.isnan(full_audio_emb).any():
        raise ValueError("Broken audio embedding with NaN values")

    indices = torch.arange(2 * 2 + 1) - 2
    audio_start_idx = 0
    audio_end_idx = audio_start_idx + audio_stride * num_frames
    center_indices = torch.arange(audio_start_idx, audio_end_idx, audio_stride).unsqueeze(1) + indices.unsqueeze(0)
    center_indices = torch.clamp(center_indices, min=0, max=full_audio_emb.shape[0] - 1)
    audio_emb = full_audio_emb[center_indices][None, ...].to(device)

    generator = torch.Generator(device=device)
    generator.manual_seed(42)

    if model_type == "avatar-v1.5" and use_distill:
        num_inference_steps = 8
        text_guidance_scale = 1.0
    else:
        num_inference_steps = 25
        text_guidance_scale = 1.0

    print(f"[LongCat-Avatar] Generating segment 1/{num_segments} (steps={num_inference_steps})...")
    output_tuple = pipe.generate_at2v(
        prompt=prompt,
        negative_prompt=negative_prompt,
        height=height,
        width=width,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        text_guidance_scale=text_guidance_scale,
        audio_guidance_scale=audio_guidance_scale,
        generator=generator,
        output_type='both',
        audio_emb=audio_emb,
        use_distill=use_distill,
    )

    output_video, latent = output_tuple
    output_video = output_video[0]
    video_frames = [(output_video[i] * 255).astype(np.uint8) for i in range(output_video.shape[0])]
    video_frames = [PIL.Image.fromarray(img) for img in video_frames]
    del output_video
    torch.cuda.empty_cache()

    all_generated_frames = video_frames
    ref_latent = latent[:, :, :1].clone()
    current_video = video_frames

    for seg_idx in range(1, num_segments):
        print(f"[LongCat-Avatar] Generating segment {seg_idx + 1}/{num_segments}...")
        audio_start_idx = audio_start_idx + audio_stride * (num_frames - num_cond_frames)
        audio_end_idx = audio_start_idx + audio_stride * num_frames
        center_indices = torch.arange(audio_start_idx, audio_end_idx, audio_stride).unsqueeze(1) + indices.unsqueeze(0)
        center_indices = torch.clamp(center_indices, min=0, max=full_audio_emb.shape[0] - 1)
        audio_emb = full_audio_emb[center_indices][None, ...].to(device)

        output_tuple = pipe.generate_avc(
            video=current_video,
            video_latent=latent,
            prompt=prompt,
            negative_prompt=negative_prompt,
            height=height,
            width=width,
            num_frames=num_frames,
            num_cond_frames=num_cond_frames,
            num_inference_steps=num_inference_steps,
            text_guidance_scale=text_guidance_scale,
            audio_guidance_scale=audio_guidance_scale,
            generator=generator,
            output_type='both',
            use_kv_cache=True,
            offload_kv_cache=False,
            enhance_hf=True if not use_distill else False,
            audio_emb=audio_emb,
            ref_latent=ref_latent,
            ref_img_index=10,
            mask_frame_range=3,
            use_distill=use_distill,
        )
        output_video, latent = output_tuple
        output_video = output_video[0]
        new_video = [(output_video[i] * 255).astype(np.uint8) for i in range(output_video.shape[0])]
        new_video = [PIL.Image.fromarray(img) for img in new_video]
        del output_video

        all_generated_frames.extend(new_video[num_cond_frames:])
        current_video = new_video
        torch.cuda.empty_cache()

    print(f"[LongCat-Avatar] Saving video to {output_path}...")
    # 将 PIL Image 列表转为 (T, H, W, C) uint8 numpy，再转为 (T, C, H, W) tensor
    frame_np = np.stack([np.array(img) for img in all_generated_frames])
    output_tensor = torch.from_numpy(frame_np).float() / 255.0
    output_tensor = output_tensor.permute(0, 3, 1, 2)  # (T, H, W, C) -> (T, C, H, W)
    os.makedirs(os.path.dirname(output_path) or OUTPUT_DIR, exist_ok=True)
    save_video_ffmpeg(output_tensor, output_path, audio_path, fps=save_fps, quality=5)
    # 防御：验证输出文件存在且非空（save_video_ffmpeg 可能静默失败）
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"LongCat-Avatar 输出文件为空或不存在: {output_path}")

    if temp_vocal_path != audio_path and os.path.exists(temp_vocal_path):
        try:
            os.remove(temp_vocal_path)
        except Exception:
            pass

    print(f"[LongCat-Avatar] Done: {output_path}")
    return output_path

def generate_tts_edge(text: str, output_path: str) -> str:
    """生成 TTS 音频 (Microsoft Edge TTS) - gTTS 失败时的备选"""
    if not text or not text.strip():
        raise ValueError("TTS text is empty")
    import edge_tts
    import asyncio
    try:
        asyncio.run(edge_tts.Communicate(text, "en-US-AriaNeural").save(output_path))
    except AttributeError:
        # Windows Python 3.7+ 需要设置事件循环策略
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(edge_tts.Communicate(text, "en-US-AriaNeural").save(output_path))
    return output_path

def generate_tts_elevenlabs(text: str, api_key: str, voice_id: str, output_path: str) -> str:
    """生成 TTS 音频 (ElevenLabs)"""
    if not api_key:
        return generate_tts_edge(text, output_path)

    try:
        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=api_key)

        audio = client.text_to_speech.convert(
            voice_id=voice_id or "EXAVITQu4vr4xnSDxMaL",  # Sarah - mature reassuring
            model_id="eleven_multilingual_v2",
            text=text
        )

        with open(output_path, 'wb') as f:
            for chunk in audio:
                f.write(chunk)
        return output_path
    except Exception as e:
        error_msg = str(e)
        if "api key" in error_msg.lower() or "invalid" in error_msg.lower() or "voice_not_found" in error_msg.lower():
            print(f"[ElevenLabs error: {error_msg[:80]}, switching to edge-tts]")
        elif "Rate limit" in error_msg or "429" in error_msg:
            print(f"[ElevenLabs rate limit, switching to edge-tts]")
        elif "connection" in error_msg.lower():
            print(f"[ElevenLabs connection failed, switching to edge-tts]")
        else:
            print(f"[ElevenLabs unexpected error: {error_msg[:80]}]")
        return generate_tts_edge(text, output_path)

def generate_tts_moss_nano(
    text: str,
    output_path: str,
    reference_audio: str = None,
    voice: str = "Junhao",
) -> str:
    """使用 MOSS-TTS-Nano (ONNX CPU) 生成英文配音

    Args:
        text: 要合成的英文文本
        output_path: 输出 WAV 路径
        reference_audio: 参考音频路径（用于 voice clone），可选
        voice: 内置声音预设（当无参考音频时使用）

    Returns:
        生成的音频文件路径
    """
    if not text or not text.strip():
        raise ValueError("TTS text is empty")

    sys.path.insert(0, os.path.join(MODEL_DIR, "MOSS-TTS-Nano_src"))

    from onnx_tts_runtime import OnnxTtsRuntime, ensure_browser_onnx_model_dir

    nano_model_dir = os.path.join(MODEL_DIR, "MOSS-TTS-Nano_src", "models")
    try:
        resolved_model_dir = ensure_browser_onnx_model_dir(nano_model_dir)
    except Exception as e:
        print(f"[MOSS-Nano] ONNX 模型访问异常 ({e})，尝试自动下载...")
        try:
            resolved_model_dir = ensure_browser_onnx_model_dir(None)
        except Exception as download_err:
            raise RuntimeError(f"MOSS-Nano 模型获取失败: {download_err}") from download_err

    runtime = OnnxTtsRuntime(
        model_dir=str(resolved_model_dir),
        thread_count=4,
        execution_provider="CPUExecutionProvider",
    )

    result = runtime.synthesize(
        text=text,
        voice=voice,
        prompt_audio_path=reference_audio,
        output_audio_path=output_path,
        enable_wetext=True,
        enable_normalize_tts_text=True,
    )

    if result is None or "audio_path" not in result:
        raise RuntimeError(f"MOSS-Nano synthesize returned invalid result: {result}")

    return result["audio_path"]

def process_video(video_path: str, target_face: str = None, config: dict = None, progress=gr.Progress(), model_size: str = "base", video_compose_mode: str = "ffmpeg", longcat_resolution: str = "720p", longcat_segments: int = 1, longcat_audio_guidance: float = 3.0, longcat_use_distill: bool = True, subtitle_embed: bool = True) -> dict:
    """
    视频处理主管道
    video_compose_mode 选项：
    - ffmpeg：CPU 音频替换（无口型同步，快速）
    - wav2lip：GPU 口型同步（需要 CUDA + Wav2Lip）
    - deeplivecam：GPU 换脸 + 口型同步（需要 CUDA + Deep-Live-Cam）
    """
    if config is None:
        config = load_config()

    # Gradio 批量模式传入 list，单文件时也可能是 list，取第一个
    if isinstance(video_path, (list, tuple)):
        video_path = video_path[0] if video_path else ""

    import io
    _temp_video_files = []
    # type="binary" 时 video_path 是 bytes，需要先写入临时文件
    if isinstance(video_path, (bytes, io.BytesIO)):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
            if isinstance(video_path, bytes):
                tmp.write(video_path)
            else:
                tmp.write(video_path.read())
            video_path = tmp.name
        _temp_video_files.append(video_path)

    # 空路径/空白路径防御（必须在 _temp_video_files 赋值之后）
    if not video_path or not video_path.strip():
        results = {
            "status": "error",
            "input_video": "",
            "output_video": None,
            "processing_time": 0,
            "steps": [],
            "errors": ["未上传视频文件"]
        }
        return results

    # 初始化 results（在任何 return 之前定义）
    results = {
        "status": "processing",
        "input_video": video_path,
        "output_video": None,
        "processing_time": 0,
        "steps": [],
        "errors": []
    }

    # 文件大小校验
    try:
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    except OSError:
        file_size_mb = 0
    if file_size_mb > MAX_FILE_SIZE_MB:
        results["status"] = "error"
        results["errors"].append(f"文件过大 ({file_size_mb:.1f}MB)，请上传 {MAX_FILE_SIZE_MB}MB 以内的视频")
        return results

    # 视频时长校验（防止超长音频 OOM）
    try:
        cmd = f'ffprobe -v quiet -show_entries format=duration -of csv=p=0 {shlex.quote(video_path)}'
        duration_str = subprocess.check_output(cmd, shell=True, text=True).strip()
        duration_sec = float(duration_str) if duration_str else 0.0
        if duration_sec <= 0:
            results["status"] = "error"
            results["errors"].append(f"视频时长异常 ({duration_sec}秒)，请上传有效视频")
            return results
        if duration_sec > 3600:
            results["status"] = "error"
            results["errors"].append(f"视频过长 ({int(duration_sec//60)}分钟)，请上传 60 分钟以内的视频")
            return results
    except Exception as e:
        print(f"[ffprobe 时长校验失败: {e}]")
        pass  # 时长获取失败不影响主流程

    start_time = datetime.now()
    # 安全处理：防止路径遍历攻击
    raw_basename = os.path.basename(video_path)
    if raw_basename:
        video_basename = os.path.splitext(raw_basename)[0]
        video_basename = re.sub(r'[^a-zA-Z0-9_\-]', '_', video_basename)
    else:
        video_basename = "video"
    unique_id = uuid.uuid4().hex[:8]
    session_prefix = f"{video_basename}_{unique_id}"

    try:
        # 取消检查
        if is_cancelled():
            raise Exception("用户取消")
        # Step 1: 提取音频
        progress(0, desc="提取音频中...")
        step1_start = datetime.now()
        audio_path = ""
        try:
            audio_path = os.path.join(OUTPUT_DIR, f"{session_prefix}_audio.wav")
            audio_path = extract_audio(video_path, audio_path)
            results["steps"].append({
                "step": "extract_audio",
                "status": "done",
                "output": audio_path,
                "time": (datetime.now() - step1_start).seconds
            })
        except Exception as e:
            results["steps"].append({
                "step": "extract_audio",
                "status": "error",
                "error": f"音频提取失败: {str(e)}"
            })
            results["errors"].append(f"音频提取: {str(e)}")
            audio_path = None

        # Step 2: 语音识别
        progress(0.2, desc="语音识别中...")
        step2_start = datetime.now()
        original_text = ""
        transcript_segments = []
        try:
            if is_cancelled():
                raise Exception("用户取消")
            if audio_path:
                transcript = transcribe_audio(audio_path, model_size, progress)
                original_text = transcript.get("text", "")
                transcript_segments = transcript.get("segments", [])
                results["steps"].append({
                    "step": "transcribe",
                    "status": "done",
                    "text_length": len(original_text),
                    "original_text": original_text[:200] + "..." if len(original_text) > 200 else original_text,
                    "segments_count": len(transcript_segments),
                    "time": (datetime.now() - step2_start).seconds
                })
            else:
                raise Exception("音频文件不存在，跳过语音识别")
        except Exception as e:
            results["steps"].append({
                "step": "transcribe",
                "status": "error",
                "error": f"语音识别失败: {str(e)}"
            })
            results["errors"].append(f"语音识别: {str(e)}")
            original_text = ""
            transcript_segments = []

        # Step 3: 翻译（分段翻译保留时间戳对应）
        progress(0.4, desc="翻译中...")
        step3_start = datetime.now()
        english_lines = []
        try:
            openai_key = config.get("openai_api_key", "")
            deepseek_key = config.get("deepseek_api_key", "")
            translation_model = config.get("translation_model", "gpt-4o")

            # 优先使用 DeepSeek（如果配置了）
            if deepseek_key and translation_model.startswith("deepseek"):
                translator = lambda text: translate_to_english_deepseek(text, deepseek_key, translation_model)
                api_key = deepseek_key
            elif openai_key:
                translator = lambda text: translate_to_english_openai(text, openai_key)
                api_key = openai_key
            else:
                api_key = None

            # 模型-key 不匹配校验
            if translation_model.startswith("deepseek") and not deepseek_key:
                raise ValueError("DeepSeek 模型已选择但未配置 DeepSeek API Key，请在设置中配置")
            elif not translation_model.startswith("deepseek") and not openai_key:
                raise ValueError("OpenAI 模型已选择但未配置 OpenAI API Key，请在设置中配置")

            if api_key and transcript_segments:
                # 分段翻译，每段单独翻，对齐时间戳
                all_en = []
                total_segs = len(transcript_segments)
                for i, seg in enumerate(transcript_segments):
                    if is_cancelled():
                        raise Exception("用户取消")
                    seg_text = seg.get("text", "").strip()
                    if seg_text:
                        en = translator(seg_text)
                        if not en or not en.strip():
                            raise RuntimeError(f"翻译返回空结果: segment={seg_text[:50]}")
                        all_en.append(en)
                    else:
                        all_en.append("")
                english_lines = all_en
                english_text = " ".join(english_lines)
            elif api_key:
                english_text = translator(original_text)
                english_lines = [english_text]
            else:
                english_text = f"[Please configure OpenAI or DeepSeek API Key to enable real translation] {original_text[:100]}..."
                english_lines = [english_text]

            results["steps"].append({
                "step": "translate",
                "status": "done",
                "translated_text": english_text[:200] + "..." if len(english_text) > 200 else english_text,
                "time": (datetime.now() - step3_start).seconds
            })
        except Exception as e:
            results["steps"].append({
                "step": "translate",
                "status": "error",
                "error": f"翻译失败: {str(e)}"
            })
            results["errors"].append(f"翻译: {str(e)}")
            english_text = f"[Translation failed] {original_text[:100]}..."
            english_lines = [english_text]

        # Step 4: TTS 生成（翻译失败时跳过）
        progress(0.6, desc="生成配音中...")
        step4_start = datetime.now()
        tts_path = ""
        translate_failed = any(s.get("step") == "translate" and s.get("status") == "error" for s in results.get("steps", []))
        if translate_failed:
            results["steps"].append({
                "step": "tts",
                "status": "error",
                "error": "翻译失败，跳过 TTS 生成"
            })
            results["errors"].append("TTS: 跳过（翻译失败）")
        else:
            try:
                tts_provider = config.get("tts_provider", "gtts")
                tts_path = os.path.join(OUTPUT_DIR, f"{session_prefix}_en.wav")

                if tts_provider == "elevenlabs":
                    elevenlabs_key = config.get("elevenlabs_api_key", "")
                    elevenlabs_voice = config.get("elevenlabs_voice_id", "")
                    tts_path = generate_tts_elevenlabs(english_text, elevenlabs_key, elevenlabs_voice, tts_path)
                elif tts_provider == "edge":
                    tts_path = generate_tts_edge(english_text, tts_path)
                elif tts_provider == "moss_nano":
                    tts_path = generate_tts_moss_nano(english_text, tts_path)
                else:
                    # gTTS as fallback, but edge-tts as primary (网络受限环境下更稳定)
                    try:
                        tts_path = generate_tts_gtts(english_text, tts_path)
                    except Exception as tts_err:
                        print(f"[gTTS failed: {tts_err}, switching to edge-tts]")
                        tts_path = generate_tts_edge(english_text, tts_path)

                if not os.path.isfile(tts_path) or os.path.getsize(tts_path) == 0:
                    raise Exception("TTS 音频生成失败（文件为空）")

                results["steps"].append({
                    "step": "tts",
                    "status": "done",
                    "output": tts_path,
                    "time": (datetime.now() - step4_start).seconds
                })
            except Exception as e:
                results["steps"].append({
                    "step": "tts",
                    "status": "error",
                    "error": f"TTS生成失败: {str(e)}"
                })
                results["errors"].append(f"TTS生成: {str(e)}")
                tts_path = ""

        # Step 5: 字幕文件生成
        progress(0.7, desc="生成字幕文件中...")
        step5_start = datetime.now()
        subtitle_path = ""
        try:
            subtitle_path = os.path.join(OUTPUT_DIR, f"{session_prefix}_en.srt")
            if transcript_segments and english_lines and english_lines[0]:
                # 有 Whisper 时间戳时生成带时间轴的 SRT
                srt_content = generate_srt_from_segments(transcript_segments, english_lines)
            else:
                # Fallback: 单段字幕，使用音频实际时长
                try:
                    if audio_path and os.path.isfile(audio_path):
                        cmd = f'ffprobe -v quiet -show_entries format=duration -of csv=p=0 {shlex.quote(audio_path)}'
                        dur_str = subprocess.check_output(cmd, shell=True, text=True).strip()
                        dur = float(dur_str) if dur_str else 0.0
                        end_time = format_srt_time(dur) if dur > 0 else "00:00:10,000"
                    else:
                        end_time = "00:00:10,000"
                except Exception:
                    end_time = "00:00:10,000"
                srt_content = f"1\n00:00:00,000 --> {end_time}\n{english_text}\n"
            os.makedirs(os.path.dirname(subtitle_path) or ".", exist_ok=True)
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            results["steps"].append({
                "step": "subtitle",
                "status": "done",
                "output": subtitle_path,
                "time": (datetime.now() - step5_start).seconds
            })
        except Exception as e:
            results["steps"].append({
                "step": "subtitle",
                "status": "error",
                "error": f"字幕生成失败: {str(e)}"
            })
            results["errors"].append(f"字幕生成: {str(e)}")
            subtitle_path = ""

        # Step 6: 视频合成
        progress(0.8, desc="合成视频中...")
        step6_start = datetime.now()
        output_video_path = ""
        try:
            output_video_path = os.path.join(OUTPUT_DIR, f"{session_prefix}_final.mp4")

            if video_compose_mode == "wav2lip":
                # Wav2Lip 口型同步（需要 GPU + Wav2Lip 模型）
                if translate_failed:
                    results["steps"].append({"step": "video_compose", "status": "error", "error": "翻译失败，跳过"})
                    results["errors"].append("视频合成: 跳过（翻译失败）")
                    output_video_path = ""
                elif not tts_path or not os.path.isfile(tts_path):
                    raise Exception("TTS 音频生成失败，无法进行视频合成")
                else:
                    print(f"[Wav2Lip] Starting lip sync with audio {tts_path}")
                    output_video_path = run_wav2lip(video_path, tts_path, output_video_path, target_face)
            elif video_compose_mode == "deeplivecam":
                # DeepLiveCam 换脸 + 口型
                if not target_face or not os.path.isfile(target_face):
                    raise Exception("DeepLiveCam 需要上传目标西方面孔图片作为换脸目标")
                if translate_failed:
                    results["steps"].append({"step": "video_compose", "status": "error", "error": "翻译失败，跳过"})
                    results["errors"].append("视频合成: 跳过（翻译失败）")
                    output_video_path = ""
                elif not tts_path or not os.path.isfile(tts_path):
                    raise Exception("TTS 音频生成失败，无法进行视频合成")
                else:
                    print(f"[DeepLiveCam] Starting face swap + lip sync")
                    swapped_video = os.path.join(OUTPUT_DIR, f"{session_prefix}_swapped.mp4")
                    run_deep_live_cam(target_face, video_path, swapped_video)
                    if not os.path.isfile(swapped_video):
                        raise RuntimeError(f"DeepLiveCam 换脸失败，未生成输出文件: {swapped_video}")
                    output_video_path = run_wav2lip(swapped_video, tts_path, output_video_path, target_face=target_face)
            elif video_compose_mode == "longcat":
                # LongCat-Video-Avatar 全生成（音频驱动欧美人物视频）
                if not target_face or not os.path.isfile(target_face):
                    raise Exception("LongCat-Avatar 需要上传参考图（欧美脸）作为生成条件")
                if translate_failed:
                    results["steps"].append({"step": "video_compose", "status": "error", "error": "翻译失败，跳过"})
                    results["errors"].append("视频合成: 跳过（翻译失败）")
                    output_video_path = ""
                elif not tts_path or not os.path.isfile(tts_path):
                    raise Exception("TTS 音频生成失败，无法进行视频合成")
                else:
                    print(f"[LongCat-Avatar] Starting audio-driven video generation")
                    output_video_path = run_longcat_avatar(
                        cond_image_path=target_face,
                        audio_path=tts_path,
                        output_path=output_video_path,
                        prompt="A western person speaking in a clear voice, with natural expressions.",
                        model_type="avatar-v1.5",
                        resolution=int(longcat_resolution.replace("p", "")),
                        num_segments=longcat_segments,
                        use_distill=longcat_use_distill,
                        audio_guidance_scale=longcat_audio_guidance,
                    )
            else:
                # 默认 FFmpeg：视频轨道复制 + 音频替换为 TTS
                if translate_failed:
                    # 翻译失败时跳过视频合成（无法生成配音）
                    results["steps"].append({
                        "step": "video_compose",
                        "status": "error",
                        "error": "翻译失败，跳过视频合成"
                    })
                    results["errors"].append("视频合成: 跳过（翻译失败）")
                    output_video_path = ""
                elif not tts_path or not os.path.isfile(tts_path):
                    raise Exception(f"TTS 音频生成失败，无法进行视频合成")
                else:
                    cmd = f'ffmpeg -y -i {shlex.quote(video_path)} -i {shlex.quote(tts_path)} -map 0:v -map 1:a -c:v copy -c:a aac -shortest {shlex.quote(output_video_path)}'
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if result.returncode != 0:
                        err = result.stderr
                        if isinstance(err, bytes):
                            err = err.decode(errors='replace')
                        raise Exception(f"ffmpeg 视频合成失败: {err or '未知错误'}")
                    # 防御：ffmpeg 成功但文件可能损坏（returncode=0不代表文件完整）
                    if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
                        raise Exception(f"ffmpeg 合成后文件为空或不存在: {output_video_path}")

            # 只有成功合成或跳过时才追加 done 步骤
            if output_video_path:
                # 字幕烧录：勾选嵌入且字幕文件存在时，将 SRT 烧入视频
                if subtitle_embed and subtitle_path and os.path.isfile(subtitle_path):
                    burned_path = burn_subtitle_ffmpeg(output_video_path, subtitle_path)
                    if burned_path != output_video_path and os.path.isfile(burned_path):
                        output_video_path = burned_path
                results["steps"].append({
                    "step": "video_compose",
                    "status": "done",
                    "output": output_video_path,
                    "time": (datetime.now() - step6_start).seconds
                })

        except Exception as e:
            results["steps"].append({
                "step": "video_compose",
                "status": "error",
                "error": f"视频合成失败: {str(e)}"
            })
            results["errors"].append(f"视频合成: {str(e)}")
            output_video_path = ""

        results["output_video"] = output_video_path
        results["subtitle_file"] = subtitle_path
        # 只有视频合成无错误时才标记 done，避免翻译/TTS失败时状态错乱
        if not any("视频合成" in err for err in results.get("errors", [])):
            results["status"] = "done"
        else:
            results["status"] = "error"
        results["processing_time"] = (datetime.now() - start_time).seconds

        progress(1.0, desc="完成！")

    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
        results["errors"].append(f"处理管道: {str(e)}")
        progress(0, desc=f"失败: {str(e)}")
    finally:
        # 清理临时音频文件
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass
        # 清理二进制上传时写入的临时视频文件
        for tmp_file in _temp_video_files:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
        # 清理 process_with_config 自身创建的临时文件
        if _temp_video_path and os.path.exists(_temp_video_path):
            try:
                os.remove(_temp_video_path)
            except Exception:
                pass
        _cancel_event.clear()  # 重置取消事件

    return results

# ============== Gradio UI ==============

def create_demo():
    default_config = load_config()

    with gr.Blocks(title="海外本土剧承制 - 本地化流水线") as demo:
        gr.Markdown("""
        # 🌐 海外本土剧承制 - 本地化流水线

        ## 使用说明

        1. **上传视频**：上传中文短剧视频文件（支持 mp4/mov/avi）
        2. **选择目标面孔**：（可选）上传目标西方面孔图片用于换脸
        3. **开始处理**：点击按钮启动自动化处理流水线
        4. **查看结果**：处理完成后可预览输出视频、下载字幕文件

        ---

        **支持功能：**
        - 📤 视频上传
        - 🔄 换脸（Deep-Live-Cam）
        - 🎤 口型同步（Wav2Lip）
        - 🔊 英文配音（TTS）
        - 📝 字幕翻译

        🔊 支持 GPU 加速，处理速度更快
        """)

        with gr.Tabs():
            with gr.Tab("🎬 处理视频"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### 📥 输入")

                        video_input = gr.File(
                            label="上传中文短剧视频",
                            type="binary",
                            file_types=[".mp4", ".mov", ".avi"],
                            file_count="multiple"
                        )

                        batch_toggle = gr.Checkbox(
                            label="批量模式（同时处理多个视频）",
                            value=False,
                            info="启用后将顺序处理多个视频"
                        )

                        clear_btn = gr.Button("🗑️ 清空上传", size="sm")

                        # 上传后视频预览 - 暂时禁用，返回 None
                        video_preview = None

                        target_face_input = gr.Image(
                            label="目标西方面孔（换脸目标）",
                            type="filepath"
                        )

                        model_size_input = gr.Dropdown(
                            label="Whisper 模型大小",
                            choices=["tiny", "base", "small", "medium", "large"],
                            value="base",
                            info="tiny最快精度低，large最慢精度高；16G内存建议 base 或 small"
                        )

                        video_compose_input = gr.Dropdown(
                            label="视频合成模式",
                            choices=[
                                ("ffmpeg（音频替换，无口型同步）", "ffmpeg"),
                                ("wav2lip（GPU 口型同步）", "wav2lip"),
                                ("deeplivecam（GPU 换脸+口型同步）", "deeplivecam"),
                                ("longcat（GPU 全生成Avatar）", "longcat"),
                            ],
                            value="ffmpeg",
                            info="GPU 服务器可选 wav2lip/deeplivecam/longcat；CPU 服务器用 ffmpeg"
                        )
                        subtitle_embed_input = gr.Checkbox(
                            label="嵌入字幕（烧入 SRT）",
                            value=True,
                            info="勾选后 SRT 字幕将烧入视频，播放器无需加载外部字幕文件"
                        )

                        longcat_params = gr.Accordion("🎯 LongCat-Avatar 高级参数", visible=False, open=False)
                        with longcat_params:
                            longcat_resolution = gr.Radio(
                                label="生成分辨率",
                                choices=["480p", "720p"],
                                value="720p",
                                info="A100 40GB 推荐 720p；显存不足时选 480p"
                            )
                            longcat_segments = gr.Slider(
                                label="视频片段数",
                                minimum=1, maximum=10, step=1,
                                value=1,
                                info="长视频分段数，每段约 3.7 秒；多段用于长内容自动续写"
                            )
                            longcat_audio_guidance = gr.Slider(
                                label="口型同步精度",
                                minimum=1.0, maximum=7.0, step=0.5,
                                value=3.0,
                                info="3.0 基础口型，5.0 高精度（速度略慢）"
                            )
                            longcat_use_distill = gr.Checkbox(
                                label="启用蒸馏加速（8步推理）",
                                value=True,
                                info="加速3倍，质量损失可忽略；关闭则25步原生推理"
                            )

                        estimate_output = gr.Textbox(
                            label="预估处理时间",
                            interactive=False,
                            lines=1,
                            show_label=True
                        )

                        metadata_output = gr.Textbox(
                            label="视频信息",
                            interactive=False,
                            lines=1,
                            show_label=True
                        )

                        process_btn = gr.Button("🚀 开始处理", variant="primary", size="lg")
                        cancel_btn = gr.Button("⏹️ 取消", variant="secondary", size="lg", visible=False)

                    with gr.Column(scale=1):
                        gr.Markdown("### 📤 输出")

                        # 进度显示
                        progress_output = gr.Progress()

                        # 状态文本
                        status_output = gr.Textbox(
                            label="处理状态",
                            interactive=False,
                            lines=3
                        )

                        # 输出视频预览 - 改为 File 类型避免 Gradio 6.x Video 组件 hash_file 问题
                        result_video = gr.File(
                            label="本地化结果视频",
                            interactive=False
                        )

                        # 原文件名展示（方便对照）
                        source_name_output = gr.Textbox(
                            label="源文件",
                            interactive=False,
                            lines=1
                        )

                        # 整体进度百分比
                        overall_progress = gr.Number(
                            label="整体进度",
                            interactive=False,
                            value=0
                        )

                        # 处理日志
                        log_output = gr.Textbox(
                            label="处理日志",
                            interactive=False,
                            lines=5,
                            show_label=True
                        )

                        # 错误信息展示
                        error_output = gr.Textbox(
                            label="错误详情",
                            interactive=False,
                            lines=3
                        )

                        # 字幕文件下载链接
                        subtitle_download = gr.File(
                            label="字幕文件下载",
                            interactive=False
                        )

            with gr.Tab("📁 输出文件"):
                gr.Markdown("""
                ## 📁 历史输出文件

                以下是 outputs 目录中的生成文件，支持直接下载。
                """)
                output_files_stats = gr.Textbox(
                    label="磁盘占用",
                    interactive=False,
                    lines=1
                )
                output_files_list = gr.File(
                    label="可下载文件",
                    interactive=False
                )

                def cleanup_old_files():
                    cleaned = 0
                    try:
                        if os.path.exists(OUTPUT_DIR):
                            import time
                            cutoff = time.time() - 7 * 24 * 3600
                            for f in os.listdir(OUTPUT_DIR):
                                fp = os.path.join(OUTPUT_DIR, f)
                                try:
                                    if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                                        os.remove(fp)
                                        cleaned += 1
                                except Exception as fp_err:
                                    print(f"[cleanup] 文件删除失败 ({fp}): {fp_err}")
                                    continue
                    except Exception as cleanup_err:
                        print(f"[cleanup_old_files] 目录操作失败: {cleanup_err}")
                    # 返回清理结果和更新后的文件列表
                    files = []
                    total_size_mb = 0
                    try:
                        if os.path.exists(OUTPUT_DIR):
                            for f in os.listdir(OUTPUT_DIR):
                                fp = os.path.join(OUTPUT_DIR, f)
                                if os.path.isfile(fp):
                                    files.append(fp)
                                    total_size_mb += os.path.getsize(fp) / (1024 * 1024)
                    except Exception as list_err:
                        print(f"[cleanup] 目录读取失败: {list_err}")
                    file_count = len(files)
                    size_str = f"{total_size_mb:.1f} MB，共 {file_count} 个文件"
                    return files, size_str, f"已清理 {cleaned} 个文件"

                def list_output_files_with_size():
                    files = []
                    total_size_mb = 0
                    try:
                        if os.path.exists(OUTPUT_DIR):
                            for f in os.listdir(OUTPUT_DIR):
                                fp = os.path.join(OUTPUT_DIR, f)
                                if os.path.isfile(fp):
                                    files.append(fp)
                                    total_size_mb += os.path.getsize(fp) / (1024 * 1024)
                    except Exception as list_err:
                        print(f"[list_output_files] 目录读取失败: {list_err}")
                    file_count = len(files)
                    size_str = f"{total_size_mb:.1f} MB，共 {file_count} 个文件"
                    return files, size_str

                initial_files, initial_size = list_output_files_with_size()
                output_files_list.value = initial_files
                output_files_stats.value = initial_size

                refresh_btn = gr.Button("🔄 刷新列表")
                refresh_btn.click(
                    fn=list_output_files_with_size,
                    outputs=[output_files_list, output_files_stats]
                )

                cleanup_btn = gr.Button("🗑️ 清理7天前文件")
                cleanup_output = gr.Textbox(label="清理结果", interactive=False, lines=1)
                cleanup_btn.click(fn=cleanup_old_files, outputs=[output_files_list, output_files_stats, cleanup_output])

            with gr.Tab("⚙️ API 配置"):
                gr.Markdown("""
                ## 🔐 API 配置

                请填写您自己的 API Key。配置将保存在服务器本地。
                """)

                with gr.Column(scale=1, min_width=400):
                    # OpenAI 配置
                    gr.Markdown("""
                    ### OpenAI (翻译)

                    [获取 API Key →](https://platform.openai.com/api-keys)
                    """)

                    openai_api_key = gr.Textbox(
                        label="OpenAI API Key",
                        value=default_config.get("openai_api_key", ""),
                        type="password",
                        placeholder="sk-xxxxxxxxxxxx",
                        info="用于 GPT-4o 翻译中文字幕"
                    )

                    # DeepSeek 配置
                    gr.Markdown("""
                    ### DeepSeek (翻译)

                    [获取 API Key →](https://platform.deepseek.com/api-keys)
                    """)

                    deepseek_api_key = gr.Textbox(
                        label="DeepSeek API Key",
                        value=default_config.get("deepseek_api_key", ""),
                        type="password",
                        placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
                        info="DeepSeek API (支持 deepseek-chat 等模型，性价比更高)"
                    )

                    translation_model = gr.Radio(
                        label="翻译模型",
                        choices=["gpt-4o", "deepseek-chat"],
                        value=default_config.get("translation_model", "gpt-4o"),
                        info="选择翻译使用的模型"
                    )

                    # ElevenLabs 配置
                    gr.Markdown("""
                    ### ElevenLabs (配音)

                    [获取 API Key →](https://elevenlabs.io/profile/api-key)
                    [选择音色 →](https://elevenlabs.io/voice-library)
                    """)

                    elevenlabs_api_key = gr.Textbox(
                        label="ElevenLabs API Key",
                        value=default_config.get("elevenlabs_api_key", ""),
                        type="password",
                        placeholder="xxxxxxxxxxxx",
                        info="用于高质量英文配音（可选，gTTS免费但效果一般）"
                    )

                    elevenlabs_voice_id = gr.Textbox(
                        label="Voice ID",
                        value=default_config.get("elevenlabs_voice_id", ""),
                        placeholder="pFZ2XhN30lalC1nlW1Pt",
                        info="ElevenLabs 音色ID，不填使用默认音色"
                    )

                    # TTS 选择
                    tts_provider = gr.Radio(
                        label="TTS 提供商",
                        choices=["gtts", "edge", "moss_nano", "elevenlabs"],
                        value=default_config.get("tts_provider", "edge"),
                        info="edge: Microsoft Edge TTS (推荐, 免API key), moss_nano: MOSS-TTS-Nano CPU (免下载), gtts: Google TTS, elevenlabs: 需要API Key"
                    )

                    save_config_btn = gr.Button("💾 保存配置", variant="primary")

                    config_output = gr.Textbox(label="保存状态", interactive=False)

                    def validate_api_key(openai_key):
                        """保存时验证 API Key 有效性"""
                        if not openai_key.strip():
                            return "⚠️ OpenAI API Key 未填写"
                        try:
                            from openai import OpenAI
                            client = OpenAI(api_key=openai_key.strip())
                            client.models.list()
                            return "✅ OpenAI API Key 验证通过"
                        except Exception as e:
                            err = str(e)
                            if "incorrect" in err.lower() or "invalid" in err.lower():
                                return f"❌ OpenAI API Key 无效: {err[:50]}"
                            else:
                                return f"⚠️ OpenAI Key 验证异常: {err[:50]}"

                    def validate_deepseek_key(deepseek_key):
                        """验证 DeepSeek API Key"""
                        if not deepseek_key.strip():
                            return None  # DeepSeek is optional
                        try:
                            from openai import OpenAI
                            client = OpenAI(api_key=deepseek_key.strip(), base_url="https://api.deepseek.com")
                            client.models.list()
                            return "✅ DeepSeek API Key 验证通过"
                        except Exception as e:
                            err = str(e)
                            if "incorrect" in err.lower() or "invalid" in err.lower() or "api_key" in err.lower():
                                return f"❌ DeepSeek API Key 无效: {err[:50]}"
                            else:
                                return f"⚠️ DeepSeek Key 验证异常: {err[:50]}"

                    def save_settings(openai_key, deepseek_key, elevenlabs_key, elevenlabs_voice, tts_choice, translation_model):
                        """保存配置，DeepSeek 和 ElevenLabs Key 在选择对应 provider 时验证"""
                        # 先验证 OpenAI (如果配置了)
                        if openai_key.strip():
                            openai_validation = validate_api_key(openai_key)
                            if "❌" in openai_validation:
                                return openai_validation
                        else:
                            openai_validation = None

                        # DeepSeek 仅在配置时验证
                        deepseek_validation = None
                        if deepseek_key.strip():
                            deepseek_validation = validate_deepseek_key(deepseek_key)
                            if "❌" in deepseek_validation:
                                return deepseek_validation

                        # ElevenLabs 仅在选择时验证
                        if tts_choice == "elevenlabs" and elevenlabs_key.strip():
                            try:
                                from elevenlabs import ElevenLabs
                                client = ElevenLabs(api_key=elevenlabs_key.strip())
                                # 尝试调用 API 验证
                                list(client.voices.get_all())
                            except Exception as e:
                                err = str(e)
                                if "api key" in err.lower() or "invalid" in err.lower() or "unauthorized" in err.lower():
                                    return f"❌ ElevenLabs API Key 无效: {err[:50]}"
                                elif "quota" in err.lower() or "limit" in err.lower():
                                    return f"⚠️ ElevenLabs 请求超限: {err[:50]}"
                                else:
                                    return f"⚠️ ElevenLabs 验证异常: {err[:50]}"

                        # 模型-key 匹配校验
                        if translation_model.startswith("deepseek") and not deepseek_key.strip():
                            return f"❌ DeepSeek 模型已选择但未配置 DeepSeek API Key"
                        if translation_model == "gpt-4o" and not openai_key.strip():
                            return f"❌ GPT-4o 模型已选择但未配置 OpenAI API Key"

                        cfg = {
                            "openai_api_key": openai_key.strip(),
                            "deepseek_api_key": deepseek_key.strip(),
                            "elevenlabs_api_key": elevenlabs_key.strip(),
                            "elevenlabs_voice_id": elevenlabs_voice.strip(),
                            "tts_provider": tts_choice,
                            "translation_model": translation_model
                        }
                        save_config(cfg)
                        msg = "配置已保存"
                        if openai_validation:
                            msg = f"{openai_validation} | {msg}"
                        if deepseek_validation:
                            msg = f"{deepseek_validation} | {msg}"
                        return msg

                    save_config_btn.click(
                        fn=save_settings,
                        inputs=[openai_api_key, deepseek_api_key, elevenlabs_api_key, elevenlabs_voice_id, tts_provider, translation_model],
                        outputs=[config_output]
                    )

        gr.Markdown("""
        ## 处理流程

        ```
        视频上传 → 音频提取 → Whisper识别 → GPT翻译 → TTS配音 → 字幕生成 → 视频合成
        ```

        ## 技术说明

        | 环节 | 技术方案 | CPU兼容性 |
        |------|---------|---------|
        | 换脸 | Deep-Live-Cam | ⚠️ 慢 |
        | 口型 | Wav2Lip | ⚠️ 慢 |
        | 配音 | gTTS / ElevenLabs | ✅ 快 |
        | 字幕 | Whisper + GPT | ✅ 快 |

        ## 注意事项

        1. **翻译**：需要 OpenAI API Key，无 Key 只跑 Mock
        2. **配音**：gTTS 免费但机械，ElevenLabs 需要 API Key
        3. **换脸/口型**：需要 GPU，CPU 版本暂不可用

        4. **模型首次加载**：Whisper base 模型约 75MB，首次加载后缓存，后续处理更快
        """)

        # 事件绑定 - 使用 config 参数
        def process_with_config(video_path, target_face, model_size, video_compose_mode, batch_mode=False, progress=gr.Progress(), longcat_resolution="720p", longcat_segments=1, longcat_audio_guidance=3.0, longcat_use_distill=True, subtitle_embed=True):
            cfg = load_config()

            # 标记原始输入是否为 list（用于批量模式判断）
            is_list_input = isinstance(video_path, (list, tuple))

            # Gradio 批量模式传入 list，单文件时也可能是 list，统一展平取第一个
            if is_list_input:
                video_path = video_path[0] if video_path else ""

            # type="binary" 时 video_path 是 bytes，需要先写入临时文件
            import io
            _temp_video_path = None
            if isinstance(video_path, (bytes, io.BytesIO)):
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                    if isinstance(video_path, bytes):
                        tmp.write(video_path)
                    else:
                        tmp.write(video_path.read())
                    video_path = tmp.name
                _temp_video_path = video_path

            # 空路径防御
            if not video_path:
                # 清理临时文件后再返回
                if _temp_video_path and os.path.exists(_temp_video_path):
                    try:
                        os.remove(_temp_video_path)
                    except Exception:
                        pass
                return "未上传视频", None, None, "未上传视频文件", "无输入", 0, ""

            # 批量模式：batch_mode=True 且原始输入是 list 时启用批量
            if batch_mode and is_list_input:
                all_status = []
                all_outputs = []
                all_errors = []
                all_logs = []

                for i, vp in enumerate(video_path):
                    if is_cancelled():
                        all_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 批次处理已取消")
                        break
                    all_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理第 {i+1}/{len(video_path)} 个视频")

                    try:
                        results = process_video(vp, target_face, cfg, progress=progress, model_size=model_size, video_compose_mode=video_compose_mode, longcat_resolution=longcat_resolution, longcat_segments=longcat_segments, longcat_audio_guidance=longcat_audio_guidance, longcat_use_distill=longcat_use_distill, subtitle_embed=subtitle_embed)
                    except Exception as e:
                        results = {"status": "error", "errors": [str(e)], "output_video": None, "steps": [], "processing_time": 0}

                    progress(0.5 + 0.5 * (i + 1) / len(video_path), desc=f"批次进度 {i+1}/{len(video_path)}...")

                    status_msg = f"视频 {i+1}: {results.get('status', 'unknown')} ({results.get('processing_time', 0)}秒)"
                    output_video = results.get("output_video")
                    if isinstance(output_video, list):
                        output_video = output_video[0] if output_video else None
                    if not output_video or not os.path.isfile(output_video):
                        output_video = None
                    errors = "\n".join(results.get("errors", [])) if results.get("errors") else "无"

                    all_status.append(status_msg)
                    all_outputs.append(output_video)
                    all_errors.append(errors)

                # 汇总
                combined_status = "\n".join(all_status)
                combined_errors = "\n---\n".join(all_errors)
                combined_logs = "\n".join(all_logs)

                # 第一个输出视频作为预览
                first_video = all_outputs[0] if all_outputs else None
                source_name = f"批量模式 ({len(video_path)} 个文件)"

                return combined_status, first_video, None, combined_errors, combined_logs, 100, source_name

            # 单文件模式
            try:
                results = process_video(video_path, target_face, cfg, progress=progress, model_size=model_size, video_compose_mode=video_compose_mode, longcat_resolution=longcat_resolution, longcat_segments=longcat_segments, longcat_audio_guidance=longcat_audio_guidance, longcat_use_distill=longcat_use_distill, subtitle_embed=subtitle_embed)
            finally:
                # 清理 process_with_config 阶段创建的临时视频文件
                if _temp_video_path and os.path.exists(_temp_video_path):
                    try:
                        os.remove(_temp_video_path)
                    except Exception:
                        pass

            # 状态信息
            status_msg = f"处理状态: {results.get('status', 'unknown')}\n"
            status_msg += f"处理时间: {results.get('processing_time', 0)}秒\n"

            # 各步骤状态
            for step in results.get("steps", []):
                step_name = step.get("step", "")
                step_status = step.get("status", "")
                step_time = step.get("time", 0)
                status_msg += f"- {step_name}: {step_status} ({step_time}s)\n"

            # 错误信息
            errors = "\n".join(results.get("errors", [])) if results.get("errors") else "无"

            # 输出视频 - empty string also treated as None to avoid Gradio File postprocess error
            output_video = results.get("output_video")
            if isinstance(output_video, list):
                output_video = output_video[0] if output_video else None
            if not output_video or not os.path.isfile(output_video):
                output_video = None

            # 字幕文件 - empty string also treated as None
            subtitle_file = results.get("subtitle_file")
            if not subtitle_file or not os.path.isfile(subtitle_file):
                subtitle_file = None

            # 日志
            log_lines = []
            log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理")
            done_count = 0
            total_count = 0
            for step in results.get("steps", []):
                log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {step.get('step')}: {step.get('status')} ({step.get('time',0)}s)")
                total_count += 1
                if step.get('status') == 'done':
                    done_count += 1
            log_msg = "\n".join(log_lines)
            overall_pct = int(done_count / total_count * 100) if total_count > 0 else 0

            # 源文件名
            source_name = os.path.basename(video_path) if video_path else ""

            return status_msg, output_video, subtitle_file if subtitle_file else None, errors, log_msg, overall_pct, source_name

        # 上传后自动预览视频 + 预估时间 + 元数据
        def update_preview_and_estimate(video_path, model_size):
            estimate = ""
            metadata = ""

            # 批量模式下只处理第一个视频
            if isinstance(video_path, (list, tuple)):
                video_path = video_path[0] if video_path else None

            if video_path:
                # type="binary" 时 video_path 是 bytes，需要先写入临时文件
                import tempfile
                import io
                _tmp_video = None
                if isinstance(video_path, (bytes, io.BytesIO)):
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                        if isinstance(video_path, bytes):
                            tmp.write(video_path)
                        else:
                            tmp.write(video_path.read())
                        video_path = tmp.name
                    _tmp_video = video_path

                try:
                    if os.path.isfile(video_path):
                        try:
                            cmd = f'ffprobe -v quiet -show_entries format=duration,size -of csv=p=0 {shlex.quote(video_path)}'
                            result = subprocess.check_output(cmd, shell=True, text=True).strip()
                            parts = result.split(',')
                            duration_str = parts[0] if len(parts) >= 1 else ''
                            size_str = parts[1] if len(parts) >= 2 else ''
                            duration_sec = float(duration_str) if duration_str else 0.0
                            size_bytes = int(size_str) if size_str and size_str.isdigit() else 0
                            # 粗略估算：base模型约 0.5x realtime，medium 约 2x，large 约 3x
                            multiplier = {"tiny": 0.3, "base": 0.5, "small": 1.0, "medium": 2.0, "large": 3.0}.get(model_size, 0.5)
                            estimated_sec = duration_sec * multiplier
                            if estimated_sec < 60:
                                estimate = f"约 {int(estimated_sec)} 秒"
                            else:
                                estimate = f"约 {int(estimated_sec // 60)} 分钟"
                            # 视频元数据
                            cmd2 = f'ffprobe -v quiet -show_entries stream=width,height,bit_rate -of csv=p=0 {shlex.quote(video_path)}'
                            info = subprocess.check_output(cmd2, shell=True, text=True).strip().split('\n')
                            width = height = bitrate = ""
                            for line in info:
                                parts = line.split(',')
                                if len(parts) >= 3:
                                    w, h, br = parts[0], parts[1], parts[2]
                                    if not width and w.isdigit():
                                        width, height, bitrate = w, h, br
                                        break
                            size_mb = size_bytes / (1024 * 1024)
                            bitrate_kbps = int(bitrate) // 1000 if bitrate and bitrate.isdigit() else "?"
                            metadata = f"📐 {width}×{height} | 📊 {bitrate_kbps} kb/s | 💾 {size_mb:.1f} MB | ⏱️ {int(duration_sec)} 秒"
                        except Exception as e:
                            print(f"[ffprobe 元数据获取失败: {e}]")
                            estimate = "无法预估"
                            metadata = ""
                finally:
                    # 清理预览阶段创建的临时视频文件
                    if _tmp_video and os.path.exists(_tmp_video):
                        try:
                            os.remove(_tmp_video)
                        except Exception:
                            pass
                return estimate, metadata

        video_input.change(
            fn=update_preview_and_estimate,
            inputs=[video_input, model_size_input],
            outputs=[estimate_output, metadata_output]
        )

        model_size_input.change(
            fn=update_preview_and_estimate,
            inputs=[video_input, model_size_input],
            outputs=[estimate_output, metadata_output]
        )

        # LongCat 参数控件显示/隐藏
        def toggle_longcat_params(mode):
            return gr.Accordion(visible=(mode == "longcat"))

        video_compose_input.change(
            fn=toggle_longcat_params,
            inputs=[video_compose_input],
            outputs=[longcat_params]
        )

        # 清空上传
        def clear_upload():
            return None, None, "", "", "", 0, False, "", "ffmpeg", True

        clear_btn.click(
            fn=clear_upload,
            outputs=[video_input, target_face_input, estimate_output, metadata_output, log_output, overall_progress, batch_toggle, video_compose_input, source_name_output, subtitle_embed_input]
        )

        # 按钮防重复：处理中禁用
        def disable_processing():
            return gr.Button(interactive=False), gr.Button(visible=True)

        def enable_processing():
            return gr.Button(interactive=True), gr.Button(visible=False)

        def reset_cancel():
            _cancel_event.clear()
            return gr.Button(visible=False)

        process_btn.click(
            fn=reset_cancel,
            outputs=[cancel_btn]
        ).then(
            fn=disable_processing,
            outputs=[process_btn, cancel_btn]
        ).then(
            fn=process_with_config,
            inputs=[video_input, target_face_input, model_size_input, video_compose_input, batch_toggle, longcat_resolution, longcat_segments, longcat_audio_guidance, longcat_use_distill, subtitle_embed_input],
            outputs=[status_output, result_video, subtitle_download, error_output, log_output, overall_progress, source_name_output]
        ).then(
            fn=enable_processing,
            outputs=[process_btn, cancel_btn]
        )

        cancel_btn.click(
            fn=cancel_processing,
            inputs=None,
            outputs=None
        )

        # 键盘快捷键 Ctrl+Enter 触发处理
        demo.load(
            fn=lambda: None,
            inputs=None,
            outputs=None,
            js="""() => {
                document.addEventListener('keydown', function(e) {
                    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                        e.preventDefault();
                        document.querySelector('button[data-testid="button-🚀-开始处理"]')?.click();
                    }
                });
            }"""
        )

    return demo

if __name__ == "__main__":
    import os
    demo = create_demo()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7890,
        share=False,
        root_path="https://px-cloud1.matpool.com:26341/"
    )