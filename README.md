# MoodTune AI

根据心情生成 3 首专属歌曲推荐的 Streamlit MVP。

## 快速开始

```bash
pip install -r requirements.txt
streamlit run app.py
```

Windows 也可双击 `start.bat` 或运行 `start.ps1`。

## 文档

- **[PROGRESS.md](./PROGRESS.md)** — 项目进度、卡点与解决方案（持续更新）

## 功能摘要

- 情绪描述 → AI 推荐 3 首歌（JSON → 卡片 UI）
- 侧边栏配置 API（DeepSeek / OpenAI 兼容）
- 网易云 / QQ 音乐一键搜索听歌
- 歌单反馈（👍/👎）与一键微调（更激昂 / 更安静）二次推荐

## DeepSeek 配置

| 项 | 值 |
|----|-----|
| Base URL | `https://api.deepseek.com` |
| 模型 | `deepseek-chat` |

详见 [PROGRESS.md](./PROGRESS.md)。
