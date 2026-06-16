"""
MoodTune AI - 情绪专属歌单推荐 MVP
运行: streamlit run app.py
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import quote_plus
from dataclasses import dataclass
from typing import Any

import httpx
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import database as db
from share_card import render_share_card_image, share_card_cache_key
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

st.set_page_config(
    page_title="MoodTune AI",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 快速模式：短提示词 + 少 token → 通常 5～15 秒内返回
SYSTEM_PROMPT_FAST = (
    "音乐推荐助手。根据用户心情推荐3首真实存在的歌。"
    "只输出JSON数组，无其他文字。每首含 title, artist, reason（理由各不超过25字）。"
    '示例:[{"title":"夜曲","artist":"周杰伦","reason":"失恋后的克制与释怀"}]'
)

SYSTEM_PROMPT_STANDARD = """分析用户情绪，推荐3首真实歌曲。仅输出JSON数组，每项含 title、artist、reason（理由一两句话）。
示例:[{"title":"歌曲","artist":"歌手","reason":"理由"}]"""

EMOTION_OPTIONS = ["高兴", "焦虑", "疲惫", "浪漫", "怀旧", "平静", "愤怒"]
SCENE_OPTIONS = ["不限", "通勤", "运动", "睡前", "学习", "工作"]

INSIGHT_SYSTEM_PROMPT = (
    "你是温暖的心理陪伴助手。根据用户近一周的情绪标签与日记摘要，"
    "用一句不超过 60 字的中文给出温柔、不评判的心情洞察，不要列点，不要称呼用户全名。"
)


@dataclass
class LlmOptions:
    system_prompt: str
    max_tokens: int
    temperature: float
    max_retries: int


def get_llm_options(fast_mode: bool) -> LlmOptions:
    if fast_mode:
        return LlmOptions(
            system_prompt=SYSTEM_PROMPT_FAST,
            max_tokens=320,
            temperature=0.3,
            max_retries=1,
        )
    return LlmOptions(
        system_prompt=SYSTEM_PROMPT_STANDARD,
        max_tokens=500,
        temperature=0.5,
        max_retries=2,
    )


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        /* 全局深色氛围 */
        .stApp {
            background: radial-gradient(ellipse at 20% 0%, #1a1a2e 0%, #0d0d12 45%, #050508 100%);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f0f14 0%, #16161f 100%);
        }
        /* 顶栏与主区域对齐深色，去掉大片留白 */
        header[data-testid="stHeader"] {
            background: #0a0a0f !important;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }
        [data-testid="stToolbar"] { right: 0.5rem; }
        .block-container {
            padding-top: 0.5rem;
            padding-bottom: 3rem;
            max-width: 820px;
        }
        [data-testid="stAppViewContainer"] > section { padding-top: 0; }

        /* 顶部 Hero */
        .hero-banner {
            position: relative;
            margin: 0 -1rem 1.75rem;
            padding: 2rem 1.5rem 1.75rem;
            border-radius: 0 0 28px 28px;
            background:
                radial-gradient(ellipse 80% 60% at 50% -20%, rgba(30,215,96,0.22) 0%, transparent 55%),
                radial-gradient(ellipse 50% 40% at 90% 10%, rgba(185,103,255,0.12) 0%, transparent 50%),
                linear-gradient(180deg, #14141c 0%, #0d0d12 100%);
            border: 1px solid rgba(255,255,255,0.05);
            border-top: none;
            text-align: center;
            overflow: hidden;
        }
        .hero-banner::before {
            content: "";
            position: absolute;
            top: -40px; right: -30px;
            width: 140px; height: 140px;
            border-radius: 50%;
            background: conic-gradient(from 0deg, #1a1a1a, #333, #1a1a1a, #444, #1a1a1a);
            opacity: 0.35;
            box-shadow: inset 0 0 0 12px #050508;
        }
        .hero-banner::after {
            content: "";
            position: absolute;
            bottom: 0; left: 0; right: 0;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(30,215,96,0.4), transparent);
        }
        .hero-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.35rem 0.9rem;
            margin-bottom: 1rem;
            border-radius: 999px;
            background: rgba(30,215,96,0.12);
            border: 1px solid rgba(30,215,96,0.35);
            color: #1ed760;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.06em;
        }
        .hero-title {
            margin: 0 0 0.5rem;
            font-size: 2.35rem;
            font-weight: 800;
            line-height: 1.2;
            color: #ffffff;
            letter-spacing: -0.03em;
        }
        .hero-title span {
            background: linear-gradient(120deg, #1ed760 0%, #5eead4 50%, #b967ff 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .hero-sub {
            margin: 0 auto 1.1rem;
            max-width: 420px;
            color: #9ca3af;
            font-size: 1.02rem;
            line-height: 1.55;
        }
        .hero-tags {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 0.5rem;
        }
        .hero-tag {
            padding: 0.35rem 0.75rem;
            border-radius: 8px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            color: #a1a1aa;
            font-size: 0.8rem;
        }

        /* 歌单区域标题 */
        .playlist-hero {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin: 1.5rem 0 1.25rem;
            padding: 1rem 1.25rem;
            border-radius: 14px;
            background: linear-gradient(135deg, rgba(30,215,96,0.12) 0%, rgba(185,103,255,0.08) 100%);
            border: 1px solid rgba(255,255,255,0.06);
        }
        .playlist-hero .vinyl {
            width: 56px; height: 56px; border-radius: 50%;
            background: conic-gradient(from 0deg, #222 0deg, #111 90deg, #333 180deg, #111 270deg, #222 360deg);
            box-shadow: inset 0 0 0 6px #0a0a0a, 0 4px 20px rgba(0,0,0,0.5);
            flex-shrink: 0;
        }
        .playlist-hero h2 {
            margin: 0; font-size: 1.35rem; color: #f5f5f7; font-weight: 700;
        }
        .playlist-hero p { margin: 0.2rem 0 0; color: #9ca3af; font-size: 0.85rem; }

        /* 单曲卡片（Streamlit bordered container） */
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: linear-gradient(145deg, rgba(28,28,36,0.95) 0%, rgba(18,18,24,0.98) 100%) !important;
            border: 1px solid rgba(255,255,255,0.08) !important;
            border-radius: 16px !important;
            box-shadow: 0 8px 32px rgba(0,0,0,0.35);
            margin-bottom: 1rem;
            padding: 0.5rem 0.25rem;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:hover {
            border-color: rgba(30,215,96,0.35) !important;
            box-shadow: 0 12px 40px rgba(30,215,96,0.1);
        }

        .track-title {
            font-size: 1.45rem;
            font-weight: 800;
            color: #ffffff;
            margin: 0 0 0.35rem 0;
            line-height: 1.3;
        }
        .track-artist {
            font-size: 0.95rem;
            color: #9ca3af;
            margin: 0 0 1rem 0;
            font-weight: 500;
        }
        .track-reason {
            margin: 0;
            padding: 0.85rem 1rem 0.85rem 1.1rem;
            border-left: 3px solid #1db954;
            background: rgba(29,185,84,0.06);
            border-radius: 0 10px 10px 0;
            color: #d4d4dc;
            font-size: 0.92rem;
            line-height: 1.65;
            font-style: italic;
        }
        .track-reason::before {
            content: "AI · ";
            color: #1ed760;
            font-style: normal;
            font-weight: 600;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }

        .album-art-img {
            width: 120px;
            height: 120px;
            border-radius: 12px;
            object-fit: cover;
            display: block;
            flex-shrink: 0;
            box-shadow: 0 8px 24px rgba(0,0,0,0.45);
            border: 1px solid rgba(255,255,255,0.08);
        }
        .album-art {
            width: 120px;
            height: 120px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.75rem;
            flex-shrink: 0;
            box-shadow: 0 8px 24px rgba(0,0,0,0.45);
        }
        .art-1 { background: linear-gradient(135deg, #1db954 0%, #169c46 100%); }
        .art-2 { background: linear-gradient(135deg, #b967ff 0%, #7c3aed 100%); }
        .art-3 { background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%); }

        .track-num {
            font-size: 0.7rem;
            font-weight: 700;
            color: #6b7280;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }

        .listen-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin-top: 1rem;
            padding-top: 0.85rem;
            border-top: 1px solid rgba(255,255,255,0.06);
        }
        .listen-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 1;
            min-width: 140px;
            padding: 0.55rem 1rem;
            border-radius: 10px;
            font-size: 0.82rem;
            font-weight: 600;
            text-decoration: none !important;
            transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
        }
        .listen-btn:hover {
            transform: translateY(-1px);
            opacity: 0.95;
        }
        .listen-btn.netease {
            color: #fff !important;
            background: linear-gradient(135deg, #e91429 0%, #c8102e 100%);
            box-shadow: 0 4px 14px rgba(233,20,41,0.35);
        }
        .listen-btn.qq {
            color: #111 !important;
            background: linear-gradient(135deg, #31c27c 0%, #12b35f 100%);
            box-shadow: 0 4px 14px rgba(49,194,124,0.3);
        }

        .feedback-panel {
            margin-top: 1.75rem;
            padding: 1.25rem 1.35rem;
            border-radius: 16px;
            background: linear-gradient(145deg, rgba(24,24,32,0.98) 0%, rgba(14,14,20,0.98) 100%);
            border: 1px solid rgba(255,255,255,0.08);
        }
        .feedback-panel h4 {
            margin: 0 0 0.35rem;
            color: #f4f4f5;
            font-size: 1.05rem;
        }
        .feedback-panel .hint {
            color: #9ca3af;
            font-size: 0.85rem;
            margin-bottom: 1rem;
        }
        .card-feedback-row {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 0.65rem;
            padding-top: 0.5rem;
            border-top: 1px dashed rgba(255,255,255,0.06);
        }
        .feedback-badge {
            font-size: 0.72rem;
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            font-weight: 600;
        }
        .feedback-badge.up {
            color: #1ed760;
            background: rgba(30,215,96,0.12);
        }
        .feedback-badge.down {
            color: #f87171;
            background: rgba(248,113,113,0.12);
        }
        .playlist-actions {
            margin: 1.25rem 0 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def extract_json_array(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("未在模型回复中找到 JSON 数组，请重试或切换快速模式")

    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, list) or len(data) < 1:
        raise ValueError("解析结果不是有效歌曲列表")

    songs: list[dict[str, Any]] = []
    for item in data[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        artist = str(item.get("artist", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if title and artist:
            songs.append({"title": title, "artist": artist, "reason": reason or "契合你此刻的心情"})

    if len(songs) < 1:
        raise ValueError("模型返回的歌曲数据不完整")
    while len(songs) < 3:
        songs.append(songs[-1])
    return songs[:3]


def normalize_base_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip().rstrip("/")
    for bad in ("/chat/completions", "/completions"):
        if u.endswith(bad):
            u = u[: -len(bad)].rstrip("/")
    return u or None


@st.cache_resource(show_spinner=False)
def create_openai_client(api_key: str, base_url: str | None, timeout_seconds: float) -> OpenAI:
    timeout = httpx.Timeout(timeout_seconds, connect=20.0)
    http_client = httpx.Client(timeout=timeout)
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "http_client": http_client,
        "timeout": timeout_seconds,
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def call_llm(
    client: OpenAI,
    model: str,
    user_mood: str,
    options: LlmOptions,
    timeout_seconds: float,
    status_slot: Any = None,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(options.max_retries + 1):
        try:
            if status_slot:
                status_slot.write(f"正在请求 API（第 {attempt + 1} 次）…")
            t0 = time.perf_counter()
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": options.system_prompt},
                    {"role": "user", "content": user_mood},
                ],
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                timeout=timeout_seconds,
                stream=True,
            )
            chunks: list[str] = []
            for event in stream:
                delta = event.choices[0].delta.content or ""
                chunks.append(delta)
            content = "".join(chunks)
            elapsed = time.perf_counter() - t0
            if status_slot:
                status_slot.write(f"API 已响应，用时 {elapsed:.1f} 秒，正在解析…")
            if not content.strip():
                raise ValueError("模型返回为空，请检查 API Key / 模型名 / 余额")
            return extract_json_array(content)
        except (APITimeoutError, APIConnectionError, RateLimitError) as e:
            last_error = e
            if attempt < options.max_retries:
                time.sleep(1.5)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("请求失败")


def test_api(
    client: OpenAI,
    model: str,
    timeout_seconds: float,
) -> tuple[bool, str]:
    try:
        t0 = time.perf_counter()
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复OK"}],
            max_tokens=5,
            timeout=min(timeout_seconds, 60.0),
        )
        text = (r.choices[0].message.content or "").strip()
        return True, f"连接成功（{time.perf_counter() - t0:.1f}s），模型回复：{text[:50]}"
    except Exception as e:
        return False, format_api_error(e, timeout_seconds)


FEEDBACK_THANKS_MSG = "感谢反馈！您的评价将用于优化下一代 MoodTune AI 推荐模型"

TUNE_ENERGETIC_ADDON = (
    "【一键微调】在理解用户原始心情的前提下，请推荐更激昂、更有力量感、"
    "节奏更明快、情绪更外放的歌曲，避免过于低沉或舒缓的风格。"
)
TUNE_CALM_ADDON = (
    "【一键微调】在理解用户原始心情的前提下，请推荐更安静、更舒缓、"
    "更适合独处与沉淀的歌曲，避免过于激烈或喧闹的风格。"
)

REFRESH_BATCH_CORE = "请生成三首全新的、与上一批不重复的歌曲。"
ADD_MORE_CORE = "请再推荐三首全新的歌曲，与已有列表不重复，风格仍契合用户心情。"


def init_session_defaults() -> None:
    db.init_db()
    for key, val in (
        ("prompt_addon", ""),
        ("last_mood", ""),
        ("feedback_history", []),
        ("auto_regenerate", False),
        ("song_list", []),
        ("song_feedback", {}),
        ("pending_action", None),
        ("mood_context", {}),
        ("last_record_id", None),
        ("session_recommendations", []),
        ("share_card_bytes", None),
        ("share_card_cache_key", None),
        ("confirm_clear_history", False),
    ):
        if key not in st.session_state:
            st.session_state[key] = val


def get_device_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_id", None):
            return str(ctx.session_id)
    except Exception:
        pass
    if "_fallback_device_id" not in st.session_state:
        st.session_state["_fallback_device_id"] = f"local_{int(time.time())}"
    return st.session_state["_fallback_device_id"]


def extract_mood_phrase(user_text: str, structured: str = "") -> str:
    if user_text.strip():
        return user_text.strip()
    match = re.search(r"【用户原话】(.+)$", structured)
    if match:
        return match.group(1).strip()
    return structured[:80] if structured else "此刻的心情"


def persist_recommendation_record(songs: list[dict[str, Any]]) -> int | None:
    if not songs:
        return None
    ctx = st.session_state.get("mood_context") or {}
    record_id = db.insert_recommendation(
        device_id=get_device_id(),
        emotion_text=ctx.get("structured") or ctx.get("user_text", ""),
        tags=ctx.get("emotions") or [],
        scene=ctx.get("scene") or "不限",
        energy=int(ctx.get("energy") or 5),
        songs=songs,
        feedback={"song_feedback": st.session_state.get("song_feedback", {})},
    )
    st.session_state["last_record_id"] = record_id
    snapshot = {
        "id": record_id,
        "timestamp": time.time(),
        "tags": ctx.get("emotions") or [],
        "scene": ctx.get("scene"),
        "energy": ctx.get("energy"),
        "user_text": ctx.get("user_text", ""),
        "songs": list(songs),
    }
    st.session_state["session_recommendations"] = [
        *st.session_state.get("session_recommendations", []),
        snapshot,
    ]
    return record_id


@st.cache_data(ttl=86400, show_spinner=False)
def cached_share_card_png(
    cache_key: str,
    mood_phrase: str,
    tags_json: str,
    songs_json: str,
    covers_json: str,
) -> bytes:
    return render_share_card_image(
        mood_phrase=mood_phrase,
        tags=json.loads(tags_json),
        songs=json.loads(songs_json),
        cover_urls=json.loads(covers_json),
    )


def song_key(title: str, artist: str) -> str:
    return f"{title.strip()}::{artist.strip()}"


def parse_song_key(key: str) -> tuple[str, str]:
    title, artist = key.split("::", 1)
    return title, artist


def get_song_list() -> list[dict[str, Any]]:
    if st.session_state.get("song_list"):
        return st.session_state["song_list"]
    legacy = st.session_state.get("last_playlist")
    return legacy if isinstance(legacy, list) else []


def set_song_list(songs: list[dict[str, Any]]) -> None:
    st.session_state["song_list"] = songs
    st.session_state["last_playlist"] = songs


def merge_songs_dedupe(
    existing: list[dict[str, Any]],
    new_songs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {song_key(s["title"], s["artist"]) for s in existing}
    merged = list(existing)
    for s in new_songs:
        k = song_key(s["title"], s["artist"])
        if k not in seen:
            seen.add(k)
            merged.append(s)
    return merged


def format_song_labels(songs: list[dict[str, Any]]) -> str:
    return "、".join(f"《{s['title']}》-{s['artist']}" for s in songs)


def get_disliked_song_labels() -> str:
    labels: list[str] = []
    for key, rating in st.session_state.get("song_feedback", {}).items():
        if rating == "down":
            title, artist = parse_song_key(key)
            labels.append(f"《{title}》-{artist}")
    return "、".join(labels)


def build_refresh_batch_addon(existing_songs: list[dict[str, Any]]) -> str:
    parts = [REFRESH_BATCH_CORE]
    if existing_songs:
        parts.append(f"【请勿重复推荐以下歌曲】{format_song_labels(existing_songs)}")
    disliked = get_disliked_song_labels()
    if disliked:
        parts.append(
            f"【负面示例·用户点踩不喜欢】{disliked}，请避免推荐相同或风格过于接近的歌曲。"
        )
    return "\n".join(parts)


def build_add_more_addon(existing_songs: list[dict[str, Any]]) -> str:
    parts = [ADD_MORE_CORE]
    if existing_songs:
        parts.append(f"【请勿重复推荐以下歌曲】{format_song_labels(existing_songs)}")
    disliked = get_disliked_song_labels()
    if disliked:
        parts.append(
            f"【负面示例·用户点踩不喜欢】{disliked}，请避免推荐相同或风格过于接近的歌曲。"
        )
    return "\n".join(parts)


def _queue_playlist_action(action: str) -> None:
    st.session_state["pending_action"] = action


def _set_song_feedback_cb(key: str, rating: str) -> None:
    st.session_state.setdefault("song_feedback", {})[key] = rating
    title, artist = parse_song_key(key)
    st.session_state["feedback_history"] = [
        *st.session_state.get("feedback_history", []),
        {
            "rating": rating,
            "title": title,
            "artist": artist,
            "ts": time.time(),
            "source": "per_song",
        },
    ]


def _mark_all_songs_disliked() -> None:
    for s in get_song_list():
        _set_song_feedback_cb(song_key(s["title"], s["artist"]), "down")


def _on_global_dislike() -> None:
    record_feedback("down")
    _mark_all_songs_disliked()
    st.session_state["show_feedback_toast"] = True


def build_structured_mood_message(
    emotions: list[str] | None,
    scene: str,
    energy: int,
    user_text: str,
) -> str:
    """将结构化选项与用户原话拼成一段自然语言，作为 LLM 的 user 消息主体。"""
    if emotions:
        tags = ",".join(emotions)
    else:
        tags = "未选择"
    parts = [
        f"【情绪标签】{tags}",
        f"【场景】{scene}",
        f"【能量值】{energy}/10",
    ]
    if user_text.strip():
        parts.append(f"【用户原话】{user_text.strip()}")
    return " ".join(parts)


def build_user_prompt(mood: str, addon: str = "") -> str:
    """mood 可为结构化描述全文；addon 为微调文案，追加在后。"""
    mood = mood.strip()
    addon = addon.strip()
    if addon:
        return f"{mood}\n\n{addon}"
    return mood


def render_mood_input_section() -> tuple[list[str], str, int, str]:
    """渲染心情结构化输入区，返回 (情绪列表, 场景, 能量值, 用户原话)。"""
    st.markdown(
        '<p style="color:#e4e4e7;font-weight:600;margin:0 0 0.75rem;font-size:1.05rem;">'
        "💭 描述你此刻的心情</p>",
        unsafe_allow_html=True,
    )

    selected_emotions = st.pills(
        "情绪标签（可多选）",
        EMOTION_OPTIONS,
        selection_mode="multi",
        default=None,
        help="选一个或多个当前情绪",
    )
    emotions: list[str] = list(selected_emotions) if selected_emotions else []

    col_scene, col_energy = st.columns([1, 1])
    with col_scene:
        scene = st.selectbox("场景", SCENE_OPTIONS, index=0)
    with col_energy:
        energy = st.slider("当前能量值", min_value=1, max_value=10, value=5)

    mood_text = st.text_area(
        "用户原话（可选补充）",
        label_visibility="collapsed",
        placeholder="例如：今天看到夕阳很感动，心里有点酸酸的…",
        height=100,
    )

    return emotions, scene, int(energy), mood_text


def has_mood_input(emotions: list[str], user_text: str) -> bool:
    return bool(emotions) or bool(user_text.strip())


def record_feedback(rating: str) -> None:
    entry = {
        "rating": rating,
        "ts": time.time(),
        "tune": st.session_state.get("prompt_addon") or None,
    }
    st.session_state["feedback_history"] = [
        *st.session_state.get("feedback_history", []),
        entry,
    ]


def generate_playlist(
    api_key: str,
    base_url: str | None,
    model: str,
    mood: str,
    options: LlmOptions,
    timeout_seconds: float,
    prompt_addon: str = "",
    status_label: str = "AI 正在读懂你的情绪，挑选歌曲中…",
    merge_mode: str = "replace",
) -> list[dict[str, Any]] | None:
    client = create_openai_client(api_key, base_url, timeout_seconds)
    status = st.empty()
    user_prompt = build_user_prompt(mood, prompt_addon)
    try:
        with st.spinner(status_label):
            songs = call_llm(
                client,
                model,
                user_prompt,
                options,
                timeout_seconds,
                status_slot=status,
            )
        if merge_mode == "append":
            merged = merge_songs_dedupe(get_song_list(), songs)
            set_song_list(merged)
            persist_recommendation_record(songs)
            status.success(f"已追加 {len(songs)} 首，当前共 {len(merged)} 首")
            return merged
        set_song_list(songs)
        persist_recommendation_record(songs)
        status.success("歌单已更新")
        st.session_state["last_mood"] = mood.strip()
        st.session_state["share_card_bytes"] = None
        st.session_state["share_card_cache_key"] = None
        return songs
    except json.JSONDecodeError as e:
        status.empty()
        st.error(f"JSON 解析失败：{e}")
    except Exception as e:
        status.empty()
        st.error(format_api_error(e, timeout_seconds))
    return None


def handle_pending_playlist_action(
    api_key: str | None,
    base_url: str | None,
    model: str,
    options: LlmOptions,
    timeout_seconds: float,
) -> None:
    action = st.session_state.pop("pending_action", None)
    if not action:
        return
    if not api_key:
        st.error("请在侧边栏填写 API Key。")
        return
    mood = st.session_state.get("last_mood", "").strip()
    if not mood:
        st.warning("缺少心情上下文，请先点击「生成专属歌单」。")
        return
    current = get_song_list()
    if action == "refresh_batch":
        addon = build_refresh_batch_addon(current)
        generate_playlist(
            api_key,
            base_url,
            model,
            mood,
            options,
            timeout_seconds,
            prompt_addon=addon,
            status_label="正在换一批全新歌曲…",
            merge_mode="replace",
        )
    elif action == "add_more":
        addon = build_add_more_addon(current)
        generate_playlist(
            api_key,
            base_url,
            model,
            mood,
            options,
            timeout_seconds,
            prompt_addon=addon,
            status_label="正在追加推荐歌曲…",
            merge_mode="append",
        )


def render_feedback_section(
    api_key: str | None,
    base_url: str | None,
    model: str,
    options: LlmOptions,
    timeout_seconds: float,
) -> None:
    st.markdown(
        """
        <div class="feedback-panel">
            <h4>📊 这套歌单满意吗？</h4>
            <p class="hint">你的反馈将帮助我们优化推荐策略；一键微调会立即重新生成歌单。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_up, col_down, _ = st.columns([1, 1, 2])
    with col_up:
        if st.button("👍 准确", key="fb_up", use_container_width=True):
            record_feedback("up")
            st.toast(FEEDBACK_THANKS_MSG, icon="✅")
    with col_down:
        st.button(
            "👎 不准",
            key="fb_down",
            use_container_width=True,
            on_click=_on_global_dislike,
        )
    if st.session_state.pop("show_feedback_toast", False):
        st.toast(FEEDBACK_THANKS_MSG, icon="✅")

    st.markdown(
        '<p style="color:#a1a1aa;font-size:0.88rem;margin:1rem 0 0.5rem;">'
        "🎚️ 一键微调 · 不满意可换个方向</p>",
        unsafe_allow_html=True,
    )
    col_e, col_c = st.columns(2)
    with col_e:
        tune_hot = st.button("🔥 更激昂一点", key="tune_energetic", use_container_width=True)
    with col_c:
        tune_calm = st.button("🌙 更安静一点", key="tune_calm", use_container_width=True)

    if tune_hot or tune_calm:
        if not api_key:
            st.warning("请先在侧边栏填写 API Key。")
            return
        mood = st.session_state.get("last_mood", "").strip()
        if not mood:
            st.warning("缺少上次心情描述，请重新输入后点击「生成专属歌单」。")
            return
        st.session_state["prompt_addon"] = TUNE_ENERGETIC_ADDON if tune_hot else TUNE_CALM_ADDON
        st.session_state["auto_regenerate"] = True
        st.rerun()

    addon = st.session_state.get("prompt_addon", "")
    if addon:
        label = "更激昂" if "激昂" in addon else "更安静"
        st.caption(f"📌 下次推荐将偏向：**{label}**（微调后自动应用）")


@st.cache_data(ttl=86400, show_spinner=False)
def get_album_art(artist: str, track: str) -> str | None:
    """从 Deezer 搜索专辑封面，缓存 24 小时。失败时返回 None。"""
    artist = artist.strip()
    track = track.strip()
    if not artist or not track:
        return None
    query = f'track:"{track}" artist:"{artist}"'
    url = f"https://api.deezer.com/search?q={quote_plus(query)}"
    try:
        response = requests.get(url, timeout=2)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("data") or []
        if not items:
            return None
        album = items[0].get("album") or {}
        cover = album.get("cover_medium")
        return cover if isinstance(cover, str) and cover.startswith("http") else None
    except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None


def render_album_cover_html(
    artist: str,
    track: str,
    fallback_class: str,
    emoji: str,
) -> str:
    cover_url = get_album_art(artist, track)
    if cover_url:
        safe_url = html.escape(cover_url, quote=True)
        safe_alt = html.escape(f"{track} - {artist}")
        return (
            f'<img class="album-art-img" src="{safe_url}" alt="{safe_alt}" '
            f'loading="lazy" referrerpolicy="no-referrer" />'
        )
    return f'<div class="album-art {fallback_class}">{emoji}</div>'


def build_search_query(title: str, artist: str) -> str:
    return f"{title.strip()} {artist.strip()}".strip()


def build_netease_url(title: str, artist: str) -> str:
    query = quote_plus(build_search_query(title, artist))
    return f"https://music.163.com/#/search/m/?s={query}"


def build_qq_music_url(title: str, artist: str) -> str:
    query = quote_plus(build_search_query(title, artist))
    return f"https://y.qq.com/n/ryqq/search?w={query}"


def render_listen_buttons(title: str, artist: str) -> None:
    netease_url = html.escape(build_netease_url(title, artist), quote=True)
    qq_url = html.escape(build_qq_music_url(title, artist), quote=True)
    st.markdown(
        f"""
        <div class="listen-actions">
            <a class="listen-btn netease" href="{netease_url}" target="_blank" rel="noopener noreferrer">
                🎵 去网易云音乐听歌
            </a>
            <a class="listen-btn qq" href="{qq_url}" target="_blank" rel="noopener noreferrer">
                🎧 去 QQ 音乐听歌
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero-banner">
            <div class="hero-badge">🎵 MOODTUNE · AI PLAYLIST</div>
            <h1 class="hero-title">MoodTune <span>AI</span></h1>
            <p class="hero-sub">你的情绪专属歌单 — 说出此刻的心情，AI 为你匹配 3 首懂你的歌</p>
            <div class="hero-tags">
                <span class="hero-tag">🧠 情绪理解</span>
                <span class="hero-tag">🎧 3 首精选</span>
                <span class="hero-tag">⚡ 秒级推荐</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_playlist_header(count: int) -> None:
    st.markdown(
        f"""
        <div class="playlist-hero">
            <div class="vinyl"></div>
            <div>
                <h2>✨ 你的专属歌单</h2>
                <p>共 {count} 首 · 根据你的心情智能匹配</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_share_card_section(songs: list[dict[str, Any]]) -> None:
    ctx = st.session_state.get("mood_context") or {}
    mood_phrase = extract_mood_phrase(
        ctx.get("user_text", ""),
        ctx.get("structured", ""),
    )
    tags = ctx.get("emotions") or []
    display_songs = songs[:3]
    while len(display_songs) < 3 and songs:
        display_songs.append(songs[-1])

    if st.button("📸 生成分享卡片", key="btn_share_card", use_container_width=True):
        covers = [
            get_album_art(s["artist"], s["title"]) for s in display_songs[:3]
        ]
        cache_key = share_card_cache_key(mood_phrase, tags, display_songs[:3])
        png_bytes = cached_share_card_png(
            cache_key,
            mood_phrase,
            json.dumps(tags, ensure_ascii=False),
            json.dumps(display_songs[:3], ensure_ascii=False),
            json.dumps(covers, ensure_ascii=False),
        )
        st.session_state["share_card_bytes"] = png_bytes
        st.session_state["share_card_cache_key"] = cache_key

    png = st.session_state.get("share_card_bytes")
    if png:
        st.image(png, caption="分享卡片预览", use_container_width=True)
        st.download_button(
            label="⬇️ 下载分享卡片 PNG",
            data=png,
            file_name=f"moodtune_share_{int(time.time())}.png",
            mime="image/png",
            use_container_width=True,
        )


def render_diary_section() -> None:
    record_id = st.session_state.get("last_record_id")
    if not record_id:
        return
    st.markdown(
        '<p style="color:#e4e4e7;font-weight:600;margin:1.25rem 0 0.5rem;">'
        "📔 心情日记（可选）</p>",
        unsafe_allow_html=True,
    )
    diary = st.text_area(
        "写几句此刻的心情（可选）",
        key=f"diary_input_{record_id}",
        placeholder="记录这一刻的想法，日后可在情绪趋势中回看…",
        height=88,
        label_visibility="collapsed",
    )
    if st.button("💾 保存日记", key=f"save_diary_{record_id}"):
        ok = db.update_diary(record_id, get_device_id(), diary)
        if ok:
            st.toast("日记已保存", icon="📔")
        else:
            st.error("保存失败，请重试")


def render_session_timeline() -> None:
    recs = st.session_state.get("session_recommendations") or []
    if len(recs) < 2:
        return
    with st.expander(f"📋 本次会话推荐记录（{len(recs)} 次）", expanded=False):
        for i, rec in enumerate(reversed(recs), start=1):
            first = rec["songs"][0]["title"] if rec.get("songs") else "—"
            tags = "、".join(rec.get("tags") or []) or "—"
            st.caption(
                f"#{i} {datetime.fromtimestamp(rec['timestamp']).strftime('%H:%M:%S')} "
                f"· {tags} · 《{first}》等 {len(rec.get('songs', []))} 首"
            )


def render_sidebar_history() -> None:
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 历史记录")
    device_id = get_device_id()
    rows = db.list_history(device_id, limit=30)

    if st.sidebar.button("🗑️ 清空历史", use_container_width=True):
        st.session_state["confirm_clear_history"] = True

    if st.session_state.get("confirm_clear_history"):
        st.sidebar.warning("确定清空本设备全部历史？")
        c1, c2 = st.sidebar.columns(2)
        with c1:
            if st.button("确认", key="confirm_clear_yes"):
                n = db.clear_history(device_id)
                st.session_state["confirm_clear_history"] = False
                st.session_state["session_recommendations"] = []
                st.sidebar.success(f"已清空 {n} 条")
                st.rerun()
        with c2:
            if st.button("取消", key="confirm_clear_no"):
                st.session_state["confirm_clear_history"] = False
                st.rerun()

    if not rows:
        st.sidebar.caption("暂无历史，生成歌单后会自动保存。")
        return

    for row in rows[:12]:
        first_title = row["songs"][0]["title"] if row["songs"] else "—"
        tags = "、".join(row["tags"]) if row["tags"] else "—"
        ts = datetime.fromtimestamp(row["timestamp"]).strftime("%m-%d %H:%M")
        with st.sidebar.expander(f"{ts} · {tags} · {first_title}", expanded=False):
            st.caption(f"场景：{row['scene']} · 能量 {row['energy']}/10")
            if row.get("diary_text"):
                st.markdown(f"*日记：{row['diary_text'][:120]}*")
            for s in row["songs"]:
                st.write(f"🎵 {s['title']} — {s['artist']}")


def generate_mood_insight(
    api_key: str,
    base_url: str | None,
    model: str,
    records: list[dict[str, Any]],
    timeout_seconds: float,
) -> str:
    tag_counts: dict[str, int] = {}
    diary_bits: list[str] = []
    for r in records:
        for t in r.get("tags") or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        if r.get("diary_text"):
            diary_bits.append(r["diary_text"][:80])

    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:6]
    summary = (
        f"情绪标签频次：{top_tags}；"
        f"日记摘录：{' / '.join(diary_bits[:5]) or '（暂无日记）'}"
    )
    client = create_openai_client(api_key, base_url, timeout_seconds)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
            {"role": "user", "content": summary},
        ],
        max_tokens=120,
        temperature=0.7,
        timeout=min(timeout_seconds, 45.0),
    )
    return (resp.choices[0].message.content or "").strip()


def render_trends_page(
    api_key: str | None,
    base_url: str | None,
    model: str,
    timeout_seconds: float,
) -> None:
    st.markdown("## 📊 情绪趋势")
    device_id = get_device_id()
    period = st.radio("统计周期", ["最近 7 天", "最近 30 天"], horizontal=True)
    days = 7 if period.startswith("最近 7") else 30
    records = db.fetch_trends(device_id, days=days)

    if len(records) < 2:
        st.info("多记录几天，就能看到你的心情图谱哦 ✨")
        st.caption("每次生成歌单后会自动记入历史；记得写几句心情日记。")
        return

    chart_rows = [
        {
            "日期": datetime.fromtimestamp(r["timestamp"]).strftime("%m-%d"),
            "能量值": r["energy"],
        }
        for r in records
    ]
    st.line_chart(chart_rows, x="日期", y="能量值", height=280)

    tag_counts: dict[str, int] = {}
    for r in records:
        for t in r.get("tags") or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    if tag_counts:
        st.markdown("#### 心情标签分布")
        st.bar_chart(tag_counts)

    st.markdown("#### ✨ AI 心情洞察")
    if api_key:
        if st.button("生成洞察", key="btn_insight"):
            try:
                with st.spinner("AI 正在读懂你的情绪轨迹…"):
                    st.session_state["mood_insight"] = generate_mood_insight(
                        api_key, base_url, model, records[-14:], timeout_seconds
                    )
            except Exception as e:
                st.warning(f"洞察生成失败：{e}")
        if st.session_state.get("mood_insight"):
            st.success(st.session_state["mood_insight"])
    else:
        st.caption("在侧边栏填写 API Key 后可生成 AI 心情洞察。")

    st.markdown("#### 📔 近期日记摘录")
    for r in reversed(records[-8:]):
        if r.get("diary_text"):
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M")
            st.markdown(f"**{ts}** — {r['diary_text']}")


def render_playlist_action_buttons() -> None:
    st.markdown('<div class="playlist-actions">', unsafe_allow_html=True)
    col_refresh, col_more = st.columns(2)
    with col_refresh:
        st.button(
            "🔄 换一批",
            key="btn_refresh_batch",
            use_container_width=True,
            on_click=_queue_playlist_action,
            args=("refresh_batch",),
            help="重新生成 3 首新歌，替换当前列表",
        )
    with col_more:
        st.button(
            "➕ 再推几首",
            key="btn_add_more",
            use_container_width=True,
            on_click=_queue_playlist_action,
            args=("add_more",),
            help="在现有列表后追加 3 首新歌",
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_song_cards(songs: list[dict[str, Any]]) -> None:
    """用 Streamlit 容器 + 列布局渲染音乐卡片，不展示原始 JSON。"""
    art_classes = ("art-1", "art-2", "art-3")
    emojis = ("🎵", "🎶", "🎧")
    song_feedback = st.session_state.get("song_feedback", {})

    for idx, song in enumerate(songs, start=1):
        title = html.escape(song["title"])
        artist = html.escape(song["artist"])
        reason = html.escape(song["reason"])
        art_class = art_classes[(idx - 1) % 3]
        emoji = emojis[(idx - 1) % 3]
        key = song_key(song["title"], song["artist"])
        safe_id = re.sub(r"[^\w]", "_", key)[:60]
        rating = song_feedback.get(key)
        badge = ""
        if rating == "up":
            badge = '<span class="feedback-badge up">已点赞</span>'
        elif rating == "down":
            badge = '<span class="feedback-badge down">已点踩</span>'

        with st.container(border=True):
            col_art, col_info = st.columns([0.17, 0.83], gap="medium")
            with col_art:
                cover_html = render_album_cover_html(
                    song["artist"],
                    song["title"],
                    art_class,
                    emoji,
                )
                st.markdown(cover_html, unsafe_allow_html=True)
            with col_info:
                st.markdown(
                    f'<p class="track-num">TRACK {idx:02d}</p>'
                    f'<p class="track-title">🎵 {title}</p>'
                    f'<p class="track-artist">🎤 {artist}</p>'
                    f'<blockquote class="track-reason">{reason}</blockquote>',
                    unsafe_allow_html=True,
                )
            fb_col1, fb_col2, fb_col3 = st.columns([1, 1, 3])
            with fb_col1:
                st.button(
                    "👍",
                    key=f"song_up_{idx}_{safe_id}",
                    on_click=_set_song_feedback_cb,
                    args=(key, "up"),
                    help="喜欢这首歌",
                )
            with fb_col2:
                st.button(
                    "👎",
                    key=f"song_down_{idx}_{safe_id}",
                    on_click=_set_song_feedback_cb,
                    args=(key, "down"),
                    help="不喜欢，换批时将作为负面示例",
                )
            with fb_col3:
                if badge:
                    st.markdown(
                        f'<div class="card-feedback-row">{badge}</div>',
                        unsafe_allow_html=True,
                    )
            render_listen_buttons(song["title"], song["artist"])


def sidebar_config() -> tuple[str | None, str | None, str, float, bool, str]:
    env_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    env_base = os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com/v1"
    env_model = os.getenv("LLM_MODEL") or "deepseek-v4-pro"

    page = st.sidebar.radio(
        "功能导航",
        ["🎧 推荐歌单", "📊 情绪趋势"],
        key="nav_page",
    )
    st.sidebar.header("⚙️ API 配置")
    api_key = st.sidebar.text_input("API Key", type="password", value=env_key, placeholder="sk-...",
                                    help="可在 .env 文件中设置 DEEPSEEK_API_KEY，无需每次手动输入")
    base_url = st.sidebar.text_input(
        "Base URL（可选）",
        value=env_base,
        help="DeepSeek 填 https://api.deepseek.com，不要加 /v1",
    )
    model = st.sidebar.text_input("模型名称", value=env_model)
    fast_mode = st.sidebar.toggle(
        "⚡ 快速模式（推荐）",
        value=True,
        help="更短提示词、更少输出，显著加快生成",
    )
    timeout_seconds = st.sidebar.slider("请求超时（秒）", 30, 180, 90, 15)

    st.sidebar.markdown("---")
    if st.sidebar.button("🔌 测试 API 连接", use_container_width=True):
        if not api_key:
            st.sidebar.error("请先填写 API Key")
        else:
            with st.sidebar.spinner("测试中…"):
                c = create_openai_client(api_key, normalize_base_url(base_url), timeout_seconds)
                ok, msg = test_api(c, model.strip() or "deepseek-chat", timeout_seconds)
            if ok:
                st.sidebar.success(msg)
            else:
                st.sidebar.error(msg)

    st.sidebar.caption(
        "**DeepSeek：** Base URL=`https://api.deepseek.com/v1`，模型=`deepseek-v4-pro`  \n"
        "**勿用** `deepseek-reasoner`（很慢）。生成不出时先点「测试 API 连接」。"
    )
    render_sidebar_history()
    return (
        api_key,
        normalize_base_url(base_url),
        model.strip() or "deepseek-chat",
        float(timeout_seconds),
        fast_mode,
        page,
    )


def format_api_error(exc: Exception, timeout_seconds: float) -> str:
    if isinstance(exc, AuthenticationError):
        return "API Key 无效或已过期，请到 DeepSeek 控制台重新复制 Key。"
    if isinstance(exc, APIStatusError):
        return f"API 返回错误 HTTP {exc.status_code}：{exc.message}"
    msg = str(exc).lower()
    if isinstance(exc, APITimeoutError) or "timed out" in msg or "timeout" in msg:
        return (
            f"请求超时（{int(timeout_seconds)} 秒）。\n"
            "1. 开启侧边栏「快速模式」\n"
            "2. 点「测试 API 连接」看是否能通\n"
            "3. 检查网络/VPN 能否访问 api.deepseek.com\n"
            "4. 确认账户有余额"
        )
    if isinstance(exc, APIConnectionError):
        return f"无法连接 API：{exc}\n请检查网络、代理，以及 Base URL 是否为 https://api.deepseek.com"
    return str(exc)


def main() -> None:
    inject_styles()
    init_session_defaults()

    api_key, base_url, model, timeout_seconds, fast_mode, page = sidebar_config()
    options = get_llm_options(fast_mode)

    if page == "📊 情绪趋势":
        render_trends_page(api_key, base_url, model, timeout_seconds)
        return

    render_hero()

    emotions, scene, energy, mood_text = render_mood_input_section()
    structured_mood = build_structured_mood_message(emotions, scene, energy, mood_text)
    st.session_state["mood_context"] = {
        "emotions": emotions,
        "scene": scene,
        "energy": energy,
        "user_text": mood_text,
        "structured": structured_mood,
    }

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        generate = st.button("🎧 生成专属歌单", type="primary", use_container_width=True)

    if generate:
        if not has_mood_input(emotions, mood_text):
            st.warning("请至少选择一个情绪标签，或填写用户原话。")
            return
        if not api_key:
            st.error("请在侧边栏填写 API Key。")
            return
        st.session_state["prompt_addon"] = ""
        generate_playlist(
            api_key,
            base_url,
            model,
            structured_mood,
            options,
            timeout_seconds,
            status_label=f"正在生成（{'快速' if fast_mode else '标准'}模式）…",
        )

    if st.session_state.pop("auto_regenerate", False):
        if not api_key:
            st.error("请在侧边栏填写 API Key。")
        else:
            mood = st.session_state.get("last_mood", "").strip() or structured_mood
            addon = st.session_state.get("prompt_addon", "")
            if mood:
                generate_playlist(
                    api_key,
                    base_url,
                    model,
                    mood,
                    options,
                    timeout_seconds,
                    prompt_addon=addon,
                    status_label="正在按您的微调意向重新推荐…",
                    merge_mode="replace",
                )
                st.session_state["prompt_addon"] = ""
            else:
                st.warning("请先描述心情并生成歌单。")

    handle_pending_playlist_action(api_key, base_url, model, options, timeout_seconds)

    songs = get_song_list()
    if songs:
        render_playlist_header(len(songs))
        render_session_timeline()
        render_song_cards(songs)
        render_playlist_action_buttons()
        render_share_card_section(songs)
        render_diary_section()
        render_feedback_section(api_key, base_url, model, options, timeout_seconds)


if __name__ == "__main__":
    main()
