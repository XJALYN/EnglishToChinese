# 本地同声传译播放器

B 站视频 + 本地流式同声传译 + **AI 一键总结** + **思维导图** + 导出。

## 为什么不是纯 Electron？

| 能力 | PyQt6 + Python | 纯 Electron |
|------|----------------|-------------|
| mpv 视频嵌入 | 原生支持 | 需 mpv.js / 外挂窗口 |
| faster-whisper | 成熟 Python 生态 | 需子进程或 WASM |
| ffmpeg 音频分流 | 直接调用 | 需打包二进制 |
| AI 面板 / 配置 UI | QWebEngine 渲染 | 天然 Web UI |

**当前架构**：Python 做重活（播放/ASR/翻译/TTS），UI 用 PyQt6；同时提供 **Electron 可选前端** 连接同一 Python API。

```
┌─────────────────────────────────────────────────────────┐
│  PyQt6 主应用 (python main.py)                          │
│  ├─ mpv 视频播放 + 同声传译管线                          │
│  ├─ 右侧面板: AI 总结 | 思维导图 | 导出                  │
│  └─ 大模型配置对话框 (可视化)                            │
├─────────────────────────────────────────────────────────┤
│  Electron 可选前端 (cd electron && npm run electron)    │
│  └─ 连接 FastAPI 后端 → 配置 / 总结 / 导图 / 导出       │
└─────────────────────────────────────────────────────────┘
```

## 安装

```bash
pip install -r requirements.txt
brew install mpv ffmpeg
cp .env.example .env   # 或自动读取 ~/.bailian/config.json
```

## 运行

### 方式一：PyQt6 完整应用（推荐，含视频播放）

```bash
python main.py
```

### 方式二：Electron + Python API

```bash
# 终端 1
python run_api.py

# 终端 2
cd electron && npm install && npm run electron
```

> 视频播放仍在 PyQt6 主应用中；Electron 负责 AI 配置、总结、思维导图。

## 功能

### 同声传译
- B 站链接 → yt-dlp 直链 → mpv 播放（原声静音）
- faster-whisper 本地 ASR → 百炼翻译 → CosyVoice TTS
- 实时字幕叠加

### AI 一键总结
- 播放过程中自动累积双语字幕
- 点击「AI 一键总结」，调用百炼大模型生成结构化 Markdown 总结
- 自动尝试拉取 B 站已有字幕作为补充

### 思维导图
- 基于字幕 + AI 总结，生成 Mermaid mindmap
- QWebEngine 可视化预览（需 `PyQt6-WebEngine`）

### 可视化大模型配置
- 点击「⚙ 大模型配置」
- 分别设置：翻译 / 总结 / 思维导图 模型
- 保存至 `config.json` 并同步 `.env`

### 导出
- 总结：Markdown / HTML / JSON
- 思维导图：Markdown (含 mermaid) / HTML (可浏览器打开)
- 「一键导出全部」批量导出 4 个文件

## 配置

| 变量 | 说明 | 默认 |
|------|------|------|
| `DASHSCOPE_API_KEY` | 百炼 API Key | 必填 |
| `TRANSLATE_MODEL` | 同声传译 | `qwen-plus` |
| `SUMMARY_MODEL` | AI 总结 | `qwen-plus` |
| `MINDMAP_MODEL` | 思维导图 | `qwen-plus` |
| `WHISPER_MODEL` | 本地 ASR | `base` |
| `TTS_VOICE` | CosyVoice 音色 | `longxiaochun_v3` |

## API 端点 (FastAPI :8765)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 读取配置 |
| PUT | `/api/settings` | 更新配置 |
| GET | `/api/transcript` | 当前字幕 |
| POST | `/api/summary` | AI 总结 |
| POST | `/api/mindmap` | 生成思维导图 |
