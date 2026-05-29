# overseas-drama-pipeline

全链路本地化 Demo - 中国短剧 → 欧美市场

## 技术栈

- **换脸**: Deep-Live-Cam
- **口型同步**: Wav2Lip  
- **配音**: Coqui TTS / ElevenLabs API
- **字幕**: Whisper + GPT-4o
- **剪辑**: FFmpeg
- **UI**: Gradio

## 快速开始

```bash
pip install -r requirements.txt
python app.py
```

## 端口

- Gradio UI: http://64.90.20.46:7860