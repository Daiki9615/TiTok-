"""動画情報と音声の取得（F-02, F-03, D-02）。TikTok 側の変更に備えて、この部分だけ差し替えられるようにしている。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HASHTAG_RE = re.compile(r"#([^\s#]+)")


def _fmt_date(info: dict[str, Any]) -> str | None:
    d = info.get("upload_date")
    if d and len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    ts = info.get("timestamp")
    if ts:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return None


def meta_from_info(info: dict[str, Any]) -> dict[str, Any]:
    """yt-dlp の情報から保存する項目だけを取り出す。"""
    caption = info.get("description") or info.get("title") or ""
    tags = _HASHTAG_RE.findall(caption)
    for t in info.get("tags") or []:
        if t and t not in tags:
            tags.append(t)
    return {
        "id": str(info.get("id")),
        "url": info.get("webpage_url") or info.get("original_url"),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "uploader_id": info.get("uploader_id") or info.get("channel_id") or "",
        "upload_date": _fmt_date(info),
        "caption": caption,
        "hashtags": tags,
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "repost_count": info.get("repost_count"),
        "save_count": info.get("save_count"),  # 取得できないことが多い
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


class YtDlpFetcher:
    """yt-dlp で動画情報を取り、音声（なければ動画ファイル）を一時フォルダに保存する。"""

    def __init__(self, quiet: bool = True):
        self.quiet = quiet

    def _opts(self, workdir: Path) -> dict[str, Any]:
        return {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noplaylist": True,
            "format": "bestaudio/best",
            "outtmpl": str(workdir / "%(id)s.%(ext)s"),
            "retries": 3,
        }

    def get_info(self, url: str, workdir: Path) -> dict[str, Any]:
        import yt_dlp

        with yt_dlp.YoutubeDL(self._opts(workdir)) as ydl:
            return ydl.extract_info(url, download=False)

    def download(self, info: dict[str, Any], workdir: Path) -> Path:
        import yt_dlp

        with yt_dlp.YoutubeDL(self._opts(workdir)) as ydl:
            result = ydl.process_ie_result(info, download=True)
            path = ydl.prepare_filename(result)
        p = Path(path)
        if not p.exists():
            cands = sorted(workdir.glob(f"{info.get('id')}.*"))
            if not cands:
                raise RuntimeError("音声ファイルを取得できませんでした")
            p = cands[0]
        return p
