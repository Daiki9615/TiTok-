"""分析（A-01〜A-08, SH-01〜SH-03）。AI は使わず、文字起こしと時刻から集計する。"""
from __future__ import annotations

import bisect
import math
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from statistics import mean
from typing import Any

from .dictionary import categories_for

HOOK_SECONDS = (3, 5)
ENDING_SECONDS = 5

STOPWORDS = set(
    """する いる ある なる れる られる せる くる 来る いく 行く 思う 言う できる やる みる 見る おる
    こと もの よう これ それ あれ ここ そこ どこ この その あの 私 僕 俺 自分 あなた みんな 皆さん
    さん ちゃん くん 方 人 感じ 時 とき 今日 今 ため 中 的 ほう 方 そう こう どう ない いい 良い
    はい うん えー あー まあ ちょっと なんか 本当 マジ 全部 一 二 三 回 個 円""".split()
)
_PUNCT_RE = re.compile(r"[\s、。！？!?,.・…「」『』（）()\[\]【】〜~ー―\-]+")


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


# ---------- 時刻付きの文字列 ----------
class Timeline:
    """文字起こし全体を 1 本の文字列にし、各文字が何秒目かを持つ。"""

    def __init__(self, rec: dict[str, Any]):
        chars: list[str] = []
        times: list[float] = []
        for s in rec.get("transcript", {}).get("segments") or []:
            words = s.get("words") or []
            if words:
                for w in words:
                    t = norm(w["word"]).strip()
                    chars.extend(t)
                    times.extend([float(w["start"])] * len(t))
            else:
                t = norm(s["text"])
                n = max(len(t), 1)
                span = max(float(s["end"]) - float(s["start"]), 0.0)
                for i, c in enumerate(t):
                    chars.append(c)
                    times.append(float(s["start"]) + span * i / n)
        self.text = "".join(chars)
        self.times = times
        segs = rec.get("transcript", {}).get("segments") or []
        last_end = float(segs[-1]["end"]) if segs else 0.0
        self.duration = float(rec.get("duration") or 0.0) or last_end

    def between(self, start: float, end: float) -> str:
        lo = bisect.bisect_left(self.times, start)
        hi = bisect.bisect_left(self.times, end)
        return self.text[lo:hi]

    def find_all(self, word: str) -> list[float]:
        w = norm(word)
        if not w:
            return []
        res, i = [], self.text.find(w)
        while i != -1:
            res.append(self.times[i])
            i = self.text.find(w, i + len(w))
        return res


# ---------- 単語分割 ----------
@lru_cache(maxsize=1)
def _tokenizer():
    from janome.tokenizer import Tokenizer

    return Tokenizer()


def content_words(text: str) -> list[str]:
    """名詞・動詞・形容詞だけを取り出す（意味の薄い言葉は除く）。"""
    return list(_content_words(text))


@lru_cache(maxsize=4096)
def _content_words(text: str) -> tuple[str, ...]:
    out = []
    for tok in _tokenizer().tokenize(norm(text)):
        pos = tok.part_of_speech.split(",")
        base = tok.base_form if tok.base_form != "*" else tok.surface
        if pos[0] == "名詞":
            if pos[1] in ("数", "非自立", "代名詞", "接尾", "副詞可能"):
                continue
        elif pos[0] in ("動詞", "形容詞"):
            if pos[1] != "自立":
                continue
        else:
            continue
        if len(base) < 2 and not re.match(r"[一-龯]", base):
            continue
        if base in STOPWORDS:
            continue
        out.append(base)
    return tuple(out)


def surface_tokens(text: str) -> list[str]:
    return [t.surface for t in _tokenizer().tokenize(norm(text)) if not _PUNCT_RE.fullmatch(t.surface)]


def _overlap(a: str, b: str) -> int:
    from difflib import SequenceMatcher

    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size


def common_phrases(texts: list[str], min_count: int = 2, top: int = 15) -> list[tuple[str, int]]:
    """複数の文の中で、2 本以上の動画に出てくる言い回し（2〜8 語のつながり）を数える。"""
    c: Counter[str] = Counter()
    for t in texts:
        toks = surface_tokens(t)
        seen = set()
        for n in range(2, 9):
            for i in range(len(toks) - n + 1):
                ph = "".join(toks[i : i + n])
                if len(ph) >= 3:
                    seen.add(ph)
        c.update(seen)
    items = [(p, k) for p, k in c.items() if k >= min_count]
    # 長い言い回しに含まれる同じ回数の短い言い回しは省く
    items.sort(key=lambda x: (-x[1], -len(x[0])))
    kept: list[tuple[str, int]] = []
    for p, k in items:
        # 同じ回数で、すでに選んだ言い回しと大きく重なるもの（1 語ずらしただけ等）は省く
        if any(k == kq and _overlap(p, q) >= 0.6 * len(p) for q, kq in kept):
            continue
        kept.append((p, k))
    return kept[:top]


# ---------- 1 本ごとの分析 ----------
def speech_rate(rec: dict[str, Any]) -> float | None:
    tl = Timeline(rec)
    chars = len(_PUNCT_RE.sub("", tl.text))
    if not tl.duration:
        return None
    return round(chars / (tl.duration / 60.0), 1)


def flow(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """つかみ（最初の 3 秒）／本題／締め（最後の 5 秒）に分けて表示する。"""
    tl = Timeline(rec)
    d = tl.duration
    hook_end = min(HOOK_SECONDS[0], d)
    end_start = max(hook_end, d - ENDING_SECONDS)
    parts = [("つかみ", 0.0, hook_end), ("本題", hook_end, end_start), ("締め", end_start, d + 0.01)]
    return [
        {"part": name, "start": round(a, 1), "end": round(min(b, d), 1), "text": tl.between(a, b)}
        for name, a, b in parts
    ]


def dictionary_hits(rec: dict[str, Any], dictionary: dict) -> list[dict[str, Any]]:
    tl = Timeline(rec)
    cap = norm(rec.get("caption") or "")
    rows = []
    for cat, words in categories_for(dictionary, rec.get("kind", "general")).items():
        for w in words:
            ts = tl.find_all(w)
            in_cap = norm(w) in cap
            if ts or in_cap:
                rows.append({"category": cat, "word": w, "count": len(ts), "first_sec": round(ts[0], 1) if ts else None, "in_caption": in_cap})
    return rows


def analyze_one(rec: dict[str, Any], dictionary: dict) -> dict[str, Any]:
    tl = Timeline(rec)
    words = Counter(content_words(tl.text))
    return {
        "id": rec["id"],
        "duration": tl.duration,
        "chars": len(_PUNCT_RE.sub("", tl.text)),
        "speech_rate": speech_rate(rec),
        "hooks": {s: tl.between(0, s) for s in HOOK_SECONDS},
        "ending": tl.between(max(0.0, tl.duration - ENDING_SECONDS), tl.duration + 0.01),
        "flow": flow(rec),
        "top_words": words.most_common(30),
        "hits": dictionary_hits(rec, dictionary),
    }


# ---------- 複数本の分析 ----------
def _num(x: Any) -> float | None:
    try:
        return float(x) if x is not None and x != "" else None
    except (TypeError, ValueError):
        return None


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def analyze_many(recs: list[dict[str, Any]], dictionary: dict) -> dict[str, Any]:
    ones = [analyze_one(r, dictionary) for r in recs]
    full_counts: Counter[str] = Counter()
    video_words: Counter[str] = Counter()
    for r in recs:
        ws = content_words(Timeline(r).text)
        full_counts.update(ws)
        video_words.update(set(ws))

    hit_agg: dict[tuple[str, str], dict[str, Any]] = {}
    for o in ones:
        for h in o["hits"]:
            k = (h["category"], h["word"])
            a = hit_agg.setdefault(k, {"category": h["category"], "word": h["word"], "videos": 0, "count": 0, "first": []})
            a["videos"] += 1
            a["count"] += h["count"]
            if h["first_sec"] is not None:
                a["first"].append(h["first_sec"])
    hits = [
        {**{k: v for k, v in a.items() if k != "first"}, "avg_first_sec": round(mean(a["first"]), 1) if a["first"] else None}
        for a in hit_agg.values()
    ]
    hits.sort(key=lambda h: (h["category"], -h["videos"], -h["count"]))

    rates = [o["speech_rate"] for o in ones if o["speech_rate"]]
    durs = [o["duration"] for o in ones if o["duration"]]
    pairs = [(o["duration"], _num(r.get("view_count"))) for o, r in zip(ones, recs)]
    pairs = [(d, v) for d, v in pairs if d and v is not None]
    return {
        "n": len(recs),
        "ones": ones,
        "top_words": [(w, full_counts[w], video_words[w]) for w, _ in full_counts.most_common(50)],
        "hook_phrases": {s: common_phrases([o["hooks"][s] for o in ones]) for s in HOOK_SECONDS},
        "ending_phrases": common_phrases([o["ending"] for o in ones]),
        "hits": hits,
        "speech_rate_avg": round(mean(rates), 1) if rates else None,
        "speech_rate_min": min(rates) if rates else None,
        "speech_rate_max": max(rates) if rates else None,
        "duration_avg": round(mean(durs), 1) if durs else None,
        "duration_views": pairs,
        "duration_views_corr": pearson([p[0] for p in pairs], [p[1] for p in pairs]),
    }


def word_vs_metrics(recs: list[dict[str, Any]], word: str) -> dict[str, Any]:
    """ある言葉を含む動画と含まない動画で、再生数などの平均を比べる（A-07）。"""
    w = norm(word)
    with_, without = [], []
    for r in recs:
        (with_ if w and w in Timeline(r).text else without).append(r)
    res: dict[str, Any] = {"word": word, "with_n": len(with_), "without_n": len(without)}
    for key, name in (("view_count", "再生数"), ("like_count", "いいね数"), ("comment_count", "コメント数")):
        a = [v for v in (_num(r.get(key)) for r in with_) if v is not None]
        b = [v for v in (_num(r.get(key)) for r in without) if v is not None]
        res[name] = (round(mean(a)) if a else None, round(mean(b)) if b else None)
    return res


GROUP_BY = {"uploader": "投稿者", "label": "ラベル", "kind": "動画の種類", "views": "再生数（上位半分・下位半分）"}


def group_videos(recs: list[dict[str, Any]], by: str) -> dict[str, list[dict[str, Any]]]:
    g: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if by == "views":
        rs = sorted([r for r in recs if _num(r.get("view_count")) is not None], key=lambda r: -_num(r["view_count"]))
        half = math.ceil(len(rs) / 2)
        for i, r in enumerate(rs):
            g["再生数 上位" if i < half else "再生数 下位"].append(r)
        return dict(g)
    for r in recs:
        if by == "uploader":
            g[r.get("uploader") or "(不明)"].append(r)
        elif by == "label":
            for lb in r.get("labels") or ["(ラベルなし)"]:
                g[lb].append(r)
        elif by == "kind":
            g[{"general": "一般", "shop": "店舗SNS"}.get(r.get("kind"), r.get("kind") or "")].append(r)
    return dict(g)


def compare(recs: list[dict[str, Any]], by: str, dictionary: dict, top: int = 10) -> list[dict[str, Any]]:
    """グループごとに頻出語・つかみ・話す速さ・辞書の言葉を並べる（A-08）。"""
    rows = []
    for name, rs in group_videos(recs, by).items():
        a = analyze_many(rs, dictionary)
        cats = Counter()
        for h in a["hits"]:
            cats[h["category"]] += h["videos"]
        views = [v for v in (_num(r.get("view_count")) for r in rs) if v is not None]
        rows.append(
            {
                "group": name,
                "n": len(rs),
                "avg_views": round(mean(views)) if views else None,
                "speech_rate": a["speech_rate_avg"],
                "avg_duration": a["duration_avg"],
                "top_words": "、".join(w for w, _, _ in a["top_words"][:top]),
                "hook_phrases": "、".join(p for p, _ in a["hook_phrases"][3][:5]),
                "dictionary": "、".join(f"{c}({k})" for c, k in cats.most_common(6)),
            }
        )
    rows.sort(key=lambda r: -r["n"])
    return rows
