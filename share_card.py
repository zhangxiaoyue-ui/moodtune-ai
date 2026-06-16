"""MoodTune AI — 分享卡片图片合成。"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1920
QR_PLACEHOLDER_URL = "https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=https://moodtune.ai"

TAG_GRADIENTS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "高兴": ((255, 183, 77), (255, 112, 67)),
    "焦虑": ((100, 130, 200), (60, 80, 150)),
    "疲惫": ((120, 120, 140), (70, 75, 95)),
    "浪漫": ((236, 120, 180), (180, 80, 140)),
    "怀旧": ((180, 150, 120), (120, 95, 75)),
    "平静": ((100, 180, 200), (60, 130, 160)),
    "愤怒": ((220, 80, 80), (140, 40, 50)),
}
DEFAULT_GRADIENT = ((30, 215, 96), (100, 80, 200))


def _pick_gradient(tags: list[str]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    for tag in tags:
        if tag in TAG_GRADIENTS:
            return TAG_GRADIENTS[tag]
    return DEFAULT_GRADIENT


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_vertical_gradient(
    draw: ImageDraw.ImageDraw,
    size: tuple[int, int],
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
) -> None:
    w, h = size
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)


def _fetch_cover_image(url: str | None, size: int = 280) -> Image.Image:
    placeholder = Image.new("RGB", (size, size), (40, 40, 50))
    if not url:
        return placeholder
    try:
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        return img.resize((size, size), Image.Resampling.LANCZOS)
    except Exception:
        return placeholder


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for ch in text:
        test = current + ch
        bbox = font.getbbox(test) if hasattr(font, "getbbox") else (0, 0, len(test) * 20, 30)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines[:4]


def render_share_card_image(
    mood_phrase: str,
    tags: list[str],
    songs: list[dict[str, Any]],
    cover_urls: list[str | None],
) -> bytes:
    top_c, bottom_c = _pick_gradient(tags)
    img = Image.new("RGB", (WIDTH, HEIGHT), top_c)
    draw = ImageDraw.Draw(img)
    _draw_vertical_gradient(draw, (WIDTH, HEIGHT), top_c, bottom_c)

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 80))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    title_font = _load_font(52, bold=True)
    song_font = _load_font(36, bold=True)
    sub_font = _load_font(28)
    brand_font = _load_font(40, bold=True)
    small_font = _load_font(26)

    tag_line = " · ".join(tags) if tags else "MoodTune"
    draw.text((WIDTH // 2, 120), tag_line, fill=(255, 255, 255), font=sub_font, anchor="mm")

    phrase = mood_phrase.strip() or "此刻的心情"
    y = 220
    for line in _wrap_text(phrase, title_font, WIDTH - 120):
        draw.text((WIDTH // 2, y), line, fill=(255, 255, 255), font=title_font, anchor="mm")
        y += 70

    covers_y = 720
    slot_w = 300
    gap = 40
    start_x = (WIDTH - (3 * slot_w + 2 * gap)) // 2
    for i in range(3):
        song = songs[i] if i < len(songs) else {"title": "", "artist": ""}
        cover_url = cover_urls[i] if i < len(cover_urls) else None
        cover = _fetch_cover_image(cover_url, 280)
        x = start_x + i * (slot_w + gap)
        img.paste(cover, (x, covers_y))
        draw.rounded_rectangle(
            [x - 4, covers_y - 4, x + 284, covers_y + 284],
            radius=16,
            outline=(255, 255, 255),
            width=3,
        )
        title = str(song.get("title", ""))[:14]
        artist = str(song.get("artist", ""))[:12]
        draw.text((x + 140, covers_y + 310), title, fill=(255, 255, 255), font=song_font, anchor="mm")
        draw.text((x + 140, covers_y + 355), artist, fill=(200, 200, 210), font=sub_font, anchor="mm")

    draw.text((WIDTH // 2, HEIGHT - 280), "MoodTune AI", fill=(30, 215, 96), font=brand_font, anchor="mm")
    draw.text((WIDTH // 2, HEIGHT - 220), "你的心情，AI 懂", fill=(220, 220, 230), font=small_font, anchor="mm")

    try:
        qr = _fetch_cover_image(QR_PLACEHOLDER_URL, 160)
        img.paste(qr, (WIDTH // 2 - 80, HEIGHT - 200))
    except Exception:
        draw.rectangle(
            [WIDTH // 2 - 80, HEIGHT - 200, WIDTH // 2 + 80, HEIGHT - 40],
            outline=(180, 180, 190),
            width=2,
        )
        draw.text((WIDTH // 2, HEIGHT - 120), "QR", fill=(200, 200, 200), font=sub_font, anchor="mm")

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def share_card_cache_key(
    mood_phrase: str,
    tags: list[str],
    songs: list[dict[str, Any]],
) -> str:
    payload = {
        "mood": mood_phrase,
        "tags": tags,
        "songs": [(s.get("title"), s.get("artist")) for s in songs[:3]],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
