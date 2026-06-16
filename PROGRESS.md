# MoodTune AI — 项目进度与问题记录

> 本文档自动维护：**进度**、**卡点**、**解决方案**。最后更新：2026-05-22

---

## 一、项目概览

| 项 | 说明 |
|---|---|
| 产品名 | MoodTune AI — 你的情绪专属歌单 |
| 技术栈 | Python 3 · Streamlit · OpenAI SDK（兼容 DeepSeek） |
| 核心路径 | 用户输入心情 → 大模型 JSON 推荐 3 首歌 → 卡片展示 → 外链听歌 → 反馈/微调 |
| 主文件 | `app.py` |
| 运行方式 | `streamlit run app.py` 或 `start.ps1` / `start.bat` |

---

## 二、进度总览

### ✅ 已完成

| 阶段 | 内容 | 状态 |
|------|------|------|
| MVP 基础架构 | Streamlit 页面、侧边栏 API 配置、OpenAI 客户端、System Prompt、JSON 解析 | ✅ |
| AI 接入 | DeepSeek / OpenAI 兼容；流式输出；快速/标准双模式 | ✅ |
| 结果展示 | 歌曲卡片（封面色块 + 歌名/歌手/推荐理由），移除原始 JSON 主展示 | ✅ |
| 视觉优化 | 深色 Spotify/网易云风格；Hero 顶栏；顶栏留白修复 | ✅ |
| 听歌闭环 | 每首歌「去网易云音乐」「去 QQ 音乐」搜索链接（`quote_plus` 编码） | ✅ |
| 反馈闭环 | 👍/👎 + Toast；🔥更激昂 / 🌙更安静 一键微调并自动二次推荐 | ✅ |
| 稳定性 | API 连接测试按钮；超时/重试；`httpx` 与 SDK 兼容修复 | ✅ |

### 🚧 待办 / 可扩展

| 项 | 说明 |
|----|------|
| 反馈持久化 | 当前 `feedback_history` 仅存于 `session_state`，可接 CSV/数据库 |
| 部署 | 未上云；本地 Streamlit 为主 |
| 单元测试 | 暂无自动化测试 |
| 多平台听歌 | 可扩展 Spotify、Apple Music 等 |

---

## 三、功能清单（与 `app.py` 对应）

```
用户输入心情
    ↓
[侧边栏] API Key · Base URL · 模型 · 快速模式 · 超时 · 测试连接
    ↓
生成专属歌单 → call_llm（流式）→ extract_json_array
    ↓
歌单 Hero + 3 × 音乐卡片 + 网易云/QQ 链接
    ↓
反馈区：点赞/踩 | 一键微调 → auto_regenerate → 追加 Prompt 再生成
```

---

## 四、卡点与解决方案

### 1. `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`

| 项 | 内容 |
|----|------|
| **现象** | 点击生成后报错，无法创建 OpenAI 客户端 |
| **原因** | 本机 `httpx>=0.28` 移除 `proxies` 参数，旧版 `openai` SDK 仍传入该参数 |
| **解决** | 显式创建 `httpx.Client` 并传入 `OpenAI(http_client=...)`；`requirements.txt` 约束 `openai>=1.58.0`、`httpx<0.29` |
| **状态** | ✅ 已解决 |

---

### 2. `Request timed out` / 一直生成不出来

| 项 | 内容 |
|----|------|
| **现象** | 等待很久后失败或无任何结果 |
| **原因** | 默认超时过短；网络访问 `api.deepseek.com` 慢；Prompt/输出过长 |
| **解决** | ① 侧边栏可调超时（默认 90s）② 快速模式：短 Prompt + `max_tokens≈320` ③ 流式响应 + 最多 2 次重试 ④ 「测试 API 连接」按钮先行验证 |
| **配置参考** | Base URL: `https://api.deepseek.com`，模型: `deepseek-chat`（勿用 `deepseek-reasoner`） |
| **状态** | ✅ 已缓解（依赖网络环境） |

---

### 3. 生成速度慢

| 项 | 内容 |
|----|------|
| **现象** | 用户等待时间过长 |
| **原因** | 长 System Prompt、大 `max_tokens`、非流式、推理模型 |
| **解决** | 默认开启「⚡ 快速模式」；`stream=True`；限制输出 token；客户端 `max_retries=0` 减少 SDK 层重试延迟 |
| **状态** | ✅ 已优化 |

---

### 4. 顶部区域空白、标题不显眼

| 项 | 内容 |
|----|------|
| **现象** | Streamlit 白顶栏 + 仅一行灰色副标题，主标题渐变在某些环境不可见 |
| **原因** | 默认 `stHeader` 样式与 `-webkit-text-fill-color: transparent` 兼容性 |
| **解决** | Hero Banner（品牌徽章、大标题、标签）；顶栏改深色；`render_hero()` 替代单行标题 |
| **状态** | ✅ 已解决 |

---

### 5. 结果仅展示 JSON，体验粗糙

| 项 | 内容 |
|----|------|
| **现象** | `st.json` 直接展示，不符合产品标准 |
| **解决** | `st.container(border=True)` + `st.columns` 卡片；blockquote 推荐理由；移除 JSON 主展示 |
| **状态** | ✅ 已解决 |

---

### 6. Agent 环境无法代为启动 Streamlit（Windows 沙箱）

| 项 | 内容 |
|----|------|
| **现象** | 自动化执行 `pip install` / `streamlit run` 无输出或沙箱报错 |
| **原因** | Cursor Windows 沙箱策略 `workspace_readwrite` 不支持 |
| **解决** | 提供 `start.ps1`、`start.bat` 供用户本机一键安装并启动 |
| **状态** | ⚠️ 环境限制；需用户本地执行 |

---

## 五、依赖与环境

```bash
pip install -r requirements.txt
# streamlit>=1.32.0  openai>=1.58.0  httpx>=0.27.0,<0.29.0

streamlit run app.py
```

**DeepSeek 推荐配置**

| 字段 | 值 |
|------|-----|
| Base URL | `https://api.deepseek.com` |
| 模型 | `deepseek-chat` |
| 快速模式 | 开启 |
| 超时 | 90～180 秒（网络差时调高） |

---

## 六、版本里程碑（时间线）

| 日期 | 里程碑 |
|------|--------|
| 2026-05-22 | MVP：`app.py` + 侧边栏 API + JSON 歌单 |
| 2026-05-22 | 修复 `proxies` / 超时；快速模式与流式 |
| 2026-05-22 | UI：音乐卡片、Hero、深色主题 |
| 2026-05-22 | 听歌闭环：网易云 / QQ 音乐搜索链接 |
| 2026-05-22 | 反馈闭环：点赞踩 + 激昂/安静微调二次推荐 |
| 2026-05-22 | 本文档 `PROGRESS.md` 建立 |

---

## 七、维护说明

- **何时更新本文档**：完成新功能、修复重要 Bug、遇到新卡点并解决后。
- **建议追加格式**：

```markdown
### N. [问题标题]
| 项 | 内容 |
|----|------|
| **现象** | … |
| **原因** | … |
| **解决** | … |
| **状态** | ✅ / 🚧 / ⚠️ |
```

---

## 八、当前结论

**后端逻辑已跑通**（DeepSeek + JSON 解析 + 流式生成）。**产品闭环已形成**：心情输入 → AI 歌单 → 平台听歌 → 反馈与 Prompt 微调。后续重点建议：**反馈数据落盘**、**Prompt A/B 策略**、可选 **部署到 Streamlit Cloud**。
