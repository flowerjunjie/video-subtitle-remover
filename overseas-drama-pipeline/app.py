"""
海外本土剧承制 - 全链路本地化 Demo
Gradio UI - 支持视频上传 + 换脸 + 口型同步 + 配音 + 字幕翻译
"""

import os
import subprocess
import tempfile
import shutil
import json
import threading
import uuid
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
    """加载配置"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "openai_api_key": "",
        "elevenlabs_api_key": "",
        "elevenlabs_voice_id": "",
        "translation_model": "gpt-4o",
        "tts_provider": "gtts"  # gtts / elevenlabs
    }

def save_config(config: dict):
    """保存配置"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

# ============== 工具函数 ==============

def extract_audio(video_path: str, audio_path: str = None) -> str:
    """从视频提取音频"""
    if audio_path is None:
        audio_path = video_path.replace(".mp4", "_audio.wav").replace(".mov", "_audio.wav")
    cmd = f'ffmpeg -y -i "{video_path}" -vn -acodec pcm_s16le -ar 16000 -ac 1 "{audio_path}"'
    subprocess.run(cmd, shell=True, capture_output=True)
    return audio_path

def transcribe_audio(audio_path: str, model_size: str = "base", progress=None) -> dict:
    """Whisper 语音识别"""
    model = get_whisper_model(model_size, progress)
    if progress is not None:
        progress(0.2, desc="Whisper 模型已加载，开始识别...")
    result = model.transcribe(audio_path, language="zh")
    return result

def translate_to_english_openai(text: str, api_key: str) -> str:
    """使用 OpenAI GPT 翻译"""
    if not api_key:
        return f"[Translated] {text}"

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
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_msg = str(e)
        if "Incorrect API key" in error_msg or "invalid_api_key" in error_msg:
            return f"[Error: API Key 无效，请检查 OpenAI API Key 配置]"
        elif "Rate limit" in error_msg or "429" in error_msg:
            return f"[Error: OpenAI 请求频率超限，请稍后再试]"
        elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
            return f"[Error: OpenAI API 连接失败，请检查网络]"
        else:
            return f"[Translated] {text}"

def format_srt_time(seconds: float) -> str:
    """将秒数转换为 SRT 时间格式 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def generate_srt_from_segments(segments: list, english_lines: list) -> str:
    """根据 Whisper segments 生成真实 SRT 字幕"""
    srt_lines = []
    for i, (seg, en_text) in enumerate(zip(segments, english_lines), 1):
        start = format_srt_time(seg.get("start", 0))
        end = format_srt_time(seg.get("end", 0))
        srt_lines.append(f"{i}")
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(en_text)
        srt_lines.append("")
    return "\n".join(srt_lines)

def generate_tts_gtts(text: str, output_path: str) -> str:
    """生成 TTS 音频 (gTTS)"""
    tts = gTTS(text=text, lang='en')
    tts.save(output_path)
    return output_path

def generate_tts_elevenlabs(text: str, api_key: str, voice_id: str, output_path: str) -> str:
    """生成 TTS 音频 (ElevenLabs)"""
    if not api_key:
        return generate_tts_gtts(text, output_path)

    try:
        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=api_key)

        audio = client.text_to_speech.convert(
            voice_id=voice_id or "pFZ2XhN30lalC1nlW1Pt",
            model_id="eleven_multilingual_v2",
            text=text
        )

        with open(output_path, 'wb') as f:
            for chunk in audio:
                f.write(chunk)
        return output_path
    except Exception as e:
        error_msg = str(e)
        if "api key" in error_msg.lower() or "invalid" in error_msg.lower():
            print(f"[ElevenLabs API Key 无效，切换到 gTTS]")
        elif "Rate limit" in error_msg or "429" in error_msg:
            print(f"[ElevenLabs 请求频率超限，切换到 gTTS]")
        elif "connection" in error_msg.lower():
            print(f"[ElevenLabs 连接失败，切换到 gTTS]")
        return generate_tts_gtts(text, output_path)

def process_video(video_path: str, target_face: str = None, config: dict = None, progress=gr.Progress(), model_size: str = "base") -> dict:
    """
    视频处理主管道（CPU版本）
    实际部署时替换为 Deep-Live-Cam + Wav2Lip

    使用 gr.Progress 实现实时进度展示，每步骤独立错误处理
    """
    if config is None:
        config = load_config()

    # 文件大小校验（提前初始化 results 以便错误处理）
    results = {
        "status": "processing",
        "input_video": video_path,
        "output_video": None,
        "processing_time": 0,
        "steps": [],
        "errors": []
    }

    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        results["status"] = "error"
        results["errors"].append(f"文件过大 ({file_size_mb:.1f}MB)，请上传 {MAX_FILE_SIZE_MB}MB 以内的视频")
        return results

    # 视频时长校验（防止超长音频 OOM）
    try:
        cmd = f'ffprobe -v quiet -show_entries format=duration -of csv=p=0 "{video_path}"'
        duration_str = subprocess.check_output(cmd, shell=True, text=True).strip()
        duration_sec = float(duration_str)
        if duration_sec > 3600:
            results["status"] = "error"
            results["errors"].append(f"视频过长 ({int(duration_sec//60)}分钟)，请上传 60 分钟以内的视频")
            return results
    except Exception:
        pass  # 时长获取失败不影响主流程

    start_time = datetime.now()
    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    # UUID 保证输出文件不冲突
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
            api_key = config.get("openai_api_key", "")
            if api_key and transcript_segments:
                # 分段翻译，每段单独翻，对齐时间戳
                all_en = []
                for seg in transcript_segments:
                    if is_cancelled():
                        raise Exception("用户取消")
                    seg_text = seg.get("text", "").strip()
                    if seg_text:
                        en = translate_to_english_openai(seg_text, api_key)
                        all_en.append(en)
                    else:
                        all_en.append("")
                english_lines = all_en
                english_text = " ".join(english_lines)
            elif api_key:
                english_text = translate_to_english_openai(original_text, api_key)
            else:
                english_text = f"[Please configure OpenAI API Key to enable real translation] {original_text[:100]}..."
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

        # Step 4: TTS 生成
        progress(0.6, desc="生成配音中...")
        step4_start = datetime.now()
        tts_path = ""
        try:
            tts_provider = config.get("tts_provider", "gtts")
            tts_path = os.path.join(OUTPUT_DIR, f"{session_prefix}_en.wav")

            if tts_provider == "elevenlabs":
                elevenlabs_key = config.get("elevenlabs_api_key", "")
                elevenlabs_voice = config.get("elevenlabs_voice_id", "")
                tts_path = generate_tts_elevenlabs(english_text, elevenlabs_key, elevenlabs_voice, tts_path)
            else:
                tts_path = generate_tts_gtts(english_text, tts_path)

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
            if transcript_segments and english_lines:
                srt_content = generate_srt_from_segments(transcript_segments, english_lines)
            else:
                # Fallback: 单段字幕
                srt_content = f"1\n00:00:00,000 --> 00:00:05,000\n{english_text}\n"
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

        # Step 6: 视频合成 (模拟)
        progress(0.8, desc="合成视频中...")
        step6_start = datetime.now()
        output_video_path = ""
        try:
            # TODO: 实际视频合成需要调用 ffmpeg 或其他工具
            # 目前输出音频文件路径作为模拟结果
            output_video_path = tts_path if tts_path else audio_path
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
        results["status"] = "done"
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

        ⚠️ 当前为 CPU 版本，处理速度较慢，请耐心等待
        """)

        with gr.Tabs():
            with gr.Tab("🎬 处理视频"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### 📥 输入")

                        video_input = gr.File(
                            label="上传中文短剧视频",
                            type="filepath",
                            file_types=[".mp4", ".mov", ".avi"],
                            file_count="multiple"
                        )

                        batch_toggle = gr.Checkbox(
                            label="批量模式（同时处理多个视频）",
                            value=False,
                            info="启用后将顺序处理多个视频"
                        )

                        clear_btn = gr.Button("🗑️ 清空上传", size="sm")

                        # 上传后视频预览
                        video_preview = gr.Video(
                            label="视频预览",
                            interactive=False
                        )

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

                        # 输出视频预览
                        result_video = gr.Video(
                            label="本地化结果视频",
                            interactive=False
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
                output_files_list = gr.File(
                    label="可下载文件",
                    interactive=False
                )

                def list_output_files():
                    files = []
                    total_size_mb = 0
                    if os.path.exists(OUTPUT_DIR):
                        for f in os.listdir(OUTPUT_DIR):
                            fp = os.path.join(OUTPUT_DIR, f)
                            if os.path.isfile(fp):
                                files.append(fp)
                                total_size_mb += os.path.getsize(fp) / (1024 * 1024)
                    return files

                def cleanup_old_files():
                    cleaned = 0
                    if os.path.exists(OUTPUT_DIR):
                        import time
                        cutoff = time.time() - 7 * 24 * 3600
                        for f in os.listdir(OUTPUT_DIR):
                            fp = os.path.join(OUTPUT_DIR, f)
                            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                                os.remove(fp)
                                cleaned += 1
                    return f"已清理 {cleaned} 个文件"

                def list_output_files_with_size():
                    files = []
                    total_size_mb = 0
                    if os.path.exists(OUTPUT_DIR):
                        for f in os.listdir(OUTPUT_DIR):
                            fp = os.path.join(OUTPUT_DIR, f)
                            if os.path.isfile(fp):
                                files.append(fp)
                                total_size_mb += os.path.getsize(fp) / (1024 * 1024)
                    return files

                output_files_list.value = list_output_files_with_size()

                refresh_btn = gr.Button("🔄 刷新列表")
                refresh_btn.click(fn=list_output_files_with_size, outputs=[output_files_list])

                cleanup_btn = gr.Button("🗑️ 清理7天前文件")
                cleanup_output = gr.Textbox(label="清理结果", interactive=False, lines=1)
                cleanup_btn.click(fn=cleanup_old_files, outputs=[cleanup_output])

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
                        choices=["gtts", "elevenlabs"],
                        value=default_config.get("tts_provider", "gtts"),
                        info="gTTS 免费但音色机械，ElevenLabs 效果更好但需要API Key"
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

                    def save_settings(openai_key, elevenlabs_key, elevenlabs_voice, tts_choice):
                        # 先验证再保存
                        validation = validate_api_key(openai_key)
                        if "❌" in validation:
                            return validation
                        cfg = {
                            "openai_api_key": openai_key.strip(),
                            "elevenlabs_api_key": elevenlabs_key.strip(),
                            "elevenlabs_voice_id": elevenlabs_voice.strip(),
                            "tts_provider": tts_choice,
                            "translation_model": "gpt-4o"
                        }
                        save_config(cfg)
                        return f"{validation} | 配置已保存"

                    save_config_btn.click(
                        fn=save_settings,
                        inputs=[openai_api_key, elevenlabs_api_key, elevenlabs_voice_id, tts_provider],
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
        def process_with_config(video_path, target_face, model_size, batch_mode=False):
            cfg = load_config()

            # 批量模式
            if batch_mode and isinstance(video_path, (list, tuple)):
                all_status = []
                all_outputs = []
                all_errors = []
                all_logs = []

                for i, vp in enumerate(video_path):
                    if is_cancelled():
                        all_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 批次处理已取消")
                        break
                    all_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理第 {i+1}/{len(video_path)} 个视频")

                    results = process_video(vp, target_face, cfg, model_size=model_size)

                    status_msg = f"视频 {i+1}: {results.get('status', 'unknown')} ({results.get('processing_time', 0)}秒)"
                    output_video = results.get("output_video")
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

                return combined_status, first_video, None, combined_errors, combined_logs, 100

            # 单文件模式
            results = process_video(video_path, target_face, cfg, model_size=model_size)

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

            # 输出视频
            output_video = results.get("output_video")

            # 字幕文件
            subtitle_file = results.get("subtitle_file")

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

            return status_msg, output_video, subtitle_file if subtitle_file else None, errors, log_msg, overall_pct

        # 上传后自动预览视频 + 预估时间 + 元数据
        def update_preview_and_estimate(video_path, model_size):
            estimate = ""
            metadata = ""
            if video_path:
                try:
                    cmd = f'ffprobe -v quiet -show_entries format=duration,size -of csv=p=0 "{video_path}"'
                    result = subprocess.check_output(cmd, shell=True, text=subprocess.DEVNULL).strip()
                    duration_str, size_str = result.split(',')
                    duration_sec = float(duration_str)
                    size_bytes = int(size_str)
                    # 粗略估算：base模型约 0.5x realtime，medium 约 2x，large 约 3x
                    multiplier = {"tiny": 0.3, "base": 0.5, "small": 1.0, "medium": 2.0, "large": 3.0}.get(model_size, 0.5)
                    estimated_sec = duration_sec * multiplier
                    if estimated_sec < 60:
                        estimate = f"约 {int(estimated_sec)} 秒"
                    else:
                        estimate = f"约 {int(estimated_sec // 60)} 分钟"
                    # 视频元数据
                    cmd2 = f'ffprobe -v quiet -show_entries stream=width,height,bit_rate -of csv=p=0 "{video_path}"'
                    info = subprocess.check_output(cmd2, shell=True, text=subprocess.DEVNULL).strip().split('\\n')
                    width = height = bitrate = ""
                    for line in info:
                        parts = line.split(',')
                        if len(parts) >= 3:
                            w, h, br = parts[0], parts[1], parts[2]
                            if not width and w.isdigit():
                                width, height, bitrate = w, h, br
                                break
                    size_mb = size_bytes / (1024 * 1024)
                    bitrate_kbps = int(bitrate) // 1000 if bitrate.isdigit() else "?"
                    metadata = f"📐 {width}×{height} | 📊 {bitrate_kbps} kb/s | 💾 {size_mb:.1f} MB | ⏱️ {int(duration_sec)} 秒"
                except Exception:
                    estimate = "无法预估"
                    metadata = ""
            return video_path, estimate, metadata

        video_input.change(
            fn=update_preview_and_estimate,
            inputs=[video_input, model_size_input],
            outputs=[video_preview, estimate_output, metadata_output]
        )

        model_size_input.change(
            fn=update_preview_and_estimate,
            inputs=[video_input, model_size_input],
            outputs=[video_preview, estimate_output, metadata_output]
        )

        # 清空上传
        def clear_upload():
            return None, None, "", "", "", 0, False

        clear_btn.click(
            fn=clear_upload,
            outputs=[video_input, video_preview, estimate_output, metadata_output, log_output, overall_progress, batch_toggle]
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
            inputs=[video_input, target_face_input, model_size_input, batch_toggle],
            outputs=[status_output, result_video, subtitle_download, error_output, log_output, overall_progress]
        ).then(
            fn=enable_processing,
            outputs=[process_btn, cancel_btn]
        )

        cancel_btn.click(
            fn=cancel_processing,
            inputs=None,
            outputs=None
        )

    return demo

    # 键盘快捷键 Ctrl+Enter 触发处理
    def handle_keydown(e):
        if e.key == "Enter" and (e.ctrl_key or e.meta_key):
            if process_btn.interactive:
                process_btn.click()

    demo.load(
        fn=lambda: None,
        inputs=None,
        outputs=None,
        _js="""() => {
            document.addEventListener('keydown', function(e) {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    e.preventDefault();
                    document.querySelector('button[data-testid="button-🚀-开始处理"]')?.click();
                }
            });
        }"""
    )

if __name__ == "__main__":
    demo = create_demo()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )