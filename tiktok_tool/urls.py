"""TikTok URL の確認と整理（F-01, F-02 の入口）。"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 通常の動画 URL（動画 ID を含む）
_VIDEO_RE = re.compile(
    r"^https?://(?:www\.|m\.)?tiktok\.com/(?:@[\w.\-]+/(?:video|photo)/|v/)(\d+)", re.I
)
# 短縮 URL（ID は取得時に解決する）
_SHORT_RE = re.compile(
    r"^https?://(?:(?:vm|vt)\.tiktok\.com/[\w\-]+|(?:www\.)?tiktok\.com/t/[\w\-]+)", re.I
)


@dataclass
class ParsedUrl:
    raw: str
    url: str | None  # 正規化した URL（無効なら None）
    video_id: str | None  # 通常 URL なら ID、短縮 URL なら None
    error: str | None = None


def parse_url(raw: str) -> ParsedUrl:
    s = raw.strip().strip("<>\"'")
    if not s:
        return ParsedUrl(raw, None, None, "空行")
    if not s.lower().startswith("http"):
        s = "https://" + s
    m = _VIDEO_RE.match(s)
    if m:
        return ParsedUrl(raw, s.split("?")[0], m.group(1))
    m = _SHORT_RE.match(s)
    if m:
        return ParsedUrl(raw, m.group(0), None)
    return ParsedUrl(raw, None, None, "TikTok の動画 URL ではありません")


def parse_many(text: str) -> tuple[list[ParsedUrl], list[ParsedUrl]]:
    """改行区切りの URL を (有効, 無効) に分ける。同じ動画の重複は 1 つにまとめる。"""
    valid: list[ParsedUrl] = []
    invalid: list[ParsedUrl] = []
    seen: set[str] = set()
    for line in re.split(r"[\r\n\s]+", text or ""):
        if not line.strip():
            continue
        p = parse_url(line)
        if p.url is None:
            invalid.append(p)
            continue
        key = p.video_id or p.url
        if key in seen:
            p.error = "重複（この入力の中で同じ動画）"
            invalid.append(p)
            continue
        seen.add(key)
        valid.append(p)
    return valid, invalid
