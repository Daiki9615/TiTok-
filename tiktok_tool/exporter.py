"""書き出し（D-06）と、画面で編集するためのテキスト変換。"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from .storage import SHEET_HEADERS, video_to_row


def fmt_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def _srt_ts(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_txt(rec: dict[str, Any], timestamps: bool = True) -> str:
    segs = rec.get("transcript", {}).get("segments") or []
    head = [
        f"URL: {rec.get('url')}",
        f"投稿者: {rec.get('uploader')}  投稿日: {rec.get('upload_date')}  長さ: {rec.get('duration')}秒",
        f"キャプション: {rec.get('caption')}",
        "",
    ]
    if timestamps:
        body = [f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs]
    else:
        body = [rec.get("transcript", {}).get("text") or ""]
    return "\n".join(head + body) + "\n"


def to_srt(rec: dict[str, Any]) -> str:
    out = []
    for i, s in enumerate(rec.get("transcript", {}).get("segments") or [], 1):
        out += [str(i), f"{_srt_ts(s['start'])} --> {_srt_ts(s['end'])}", s["text"], ""]
    return "\n".join(out)


def videos_csv(videos: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(SHEET_HEADERS)
    for r in videos:
        w.writerow(["" if v is None else v for v in video_to_row(r)])
    return "﻿" + buf.getvalue()  # Excel で文字化けしないよう BOM 付き


def rows_csv(headers: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return "﻿" + buf.getvalue()


# ---- 画面での手修正（D-04）----
_LINE_RE = re.compile(r"^\[(\d+):(\d{2})\]\s?(.*)$")


def segments_to_edit_text(segs: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs)


def apply_edit_text(segs: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """編集されたテキストを元の区切りに戻す。行数が同じなら時刻は元のまま、文字だけ差し替える。
    行数が変わった場合は、行頭の [分:秒] を時刻として使う。"""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) == len(segs):
        new = []
        for s, l in zip(segs, lines):
            m = _LINE_RE.match(l.strip())
            t = (m.group(3) if m else l).strip()
            ns = dict(s)
            if t != s["text"]:
                ns["text"] = t
                ns["words"] = []  # 単語の時刻は直した文字と合わなくなるため捨てる
            new.append(ns)
        return new
    new = []
    for l in lines:
        m = _LINE_RE.match(l.strip())
        if m:
            start = int(m.group(1)) * 60 + int(m.group(2))
            t = m.group(3).strip()
        else:
            start = new[-1]["start"] if new else 0.0
            t = l.strip()
        new.append({"start": float(start), "end": float(start), "text": t, "words": []})
    for a, b in zip(new, new[1:]):
        a["end"] = max(a["start"], b["start"])
    if new and segs:
        new[-1]["end"] = max(new[-1]["start"], segs[-1]["end"])
    return new
