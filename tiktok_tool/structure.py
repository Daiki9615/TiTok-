"""構成作成（C-01〜C-07）。骨組みは AI なしで作り、台本は Claude に渡す依頼文を作る。"""
from __future__ import annotations

from typing import Any

from .analyzer import Timeline, analyze_many
from .exporter import fmt_ts

# (パート名, 長さの割合, 入れる要素の説明)
TEMPLATES: dict[str, list[tuple[str, float, str]]] = {
    "general": [
        ("つかみ", 0.10, "最初の一言で「自分のことだ」と思わせる"),
        ("前置き・問題提起", 0.20, "見る人の悩みや状況を言葉にする"),
        ("本題", 0.50, "伝えたいことの中身（作りたい動画の内容）"),
        ("まとめ", 0.10, "一番伝えたいことを一言で言い直す"),
        ("締め・呼びかけ", 0.10, "フォロー・保存などの呼びかけ"),
    ],
    "shop": [
        ("つかみ", 0.10, "お店や看板メニューの一番の魅力を一言で"),
        ("看板メニュー・商品", 0.35, "看板メニュー・価格帯"),
        ("お店の雰囲気・人", 0.25, "店内・スタッフ・こだわり"),
        ("来店特典", 0.15, "来店特典"),
        ("来店誘導", 0.15, "場所・最寄り駅・営業時間・予約方法"),
    ],
}

SHOP_FIELDS = [
    ("name", "店名"), ("category", "業種"), ("place", "場所・最寄り駅"), ("hours", "営業時間・定休日"),
    ("menu", "看板商品・メニュー"), ("price", "価格帯"), ("benefit", "来店特典"), ("reserve", "予約方法"),
    ("other", "その他・伝えたいこと"),
]

_SHOP_PART_FIELDS = {
    "看板メニュー・商品": ["menu", "price"],
    "お店の雰囲気・人": ["other"],
    "来店特典": ["benefit"],
    "来店誘導": ["place", "hours", "reserve"],
    "つかみ": ["name", "menu"],
}


def allocate(duration: float, parts: list[tuple[str, float, str]]) -> list[tuple[str, float, float, str]]:
    """全体の秒数を割合で分ける。つかみは 2〜3 秒、締めは最低 3 秒にする。"""
    d = max(float(duration), 5.0)
    ratios = [r for _, r, _ in parts]
    secs = [d * r for r in ratios]
    secs[0] = min(max(secs[0], 2.0), 3.0)
    secs[-1] = max(secs[-1], 3.0)
    rest = d - secs[0] - secs[-1]
    mid_total = sum(ratios[1:-1]) or 1.0
    for i in range(1, len(parts) - 1):
        secs[i] = rest * ratios[i] / mid_total
    out, t = [], 0.0
    for (name, _, desc), s in zip(parts, secs):
        out.append((name, round(t), round(t + s), desc))
        t += s
    out[-1] = (out[-1][0], out[-1][1], round(d), out[-1][3])
    return out


def _ref_label(i: int) -> str:
    return "参考動画" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i % 26]


def build_skeleton(
    refs: list[dict[str, Any]],
    dictionary: dict,
    intent: str,
    duration: float = 30,
    kind: str = "general",
    mood: str = "",
    shop: dict[str, str] | None = None,
) -> dict[str, Any]:
    parts = allocate(duration, TEMPLATES.get(kind, TEMPLATES["general"]))
    analysis = analyze_many(refs, dictionary) if refs else None
    shop = shop or {}
    rows = []
    for idx, (name, a, b, desc) in enumerate(parts):
        elems = desc
        if kind == "shop":
            vals = [f"{lbl}: {shop[k]}" for k, lbl in SHOP_FIELDS if k in _SHOP_PART_FIELDS.get(name, []) and shop.get(k)]
            if vals:
                elems += "（" + " / ".join(vals) + "）"
        elif name == "本題" and intent:
            elems += f"（{intent[:60]}）"
        phrases, ref_parts = [], []
        if analysis:
            if idx == 0:
                phrases = [p for p, _ in analysis["hook_phrases"][3][:3]]
            elif idx == len(parts) - 1:
                phrases = [p for p, _ in analysis["ending_phrases"][:3]]
            # 参考動画の同じ位置（割合）で話していたこと
            for i, r in enumerate(refs[:3]):
                tl = Timeline(r)
                if not tl.duration:
                    continue
                ra, rb = tl.duration * a / duration, tl.duration * b / duration
                txt = tl.between(ra, rb).strip()
                if txt:
                    ref_parts.append(f"{_ref_label(i)} {fmt_ts(ra)}〜{fmt_ts(rb)}「{txt[:40]}{'…' if len(txt) > 40 else ''}」")
        rows.append(
            {
                "time": f"{a}〜{b}秒",
                "part": name,
                "elements": elems,
                "phrases": "、".join(phrases),
                "reference": " / ".join(ref_parts),
            }
        )
    rate = analysis["speech_rate_avg"] if analysis else None
    return {
        "kind": kind,
        "intent": intent,
        "duration": duration,
        "mood": mood,
        "shop": shop if kind == "shop" else {},
        "ref_ids": [r["id"] for r in refs],
        "rows": rows,
        "speech_rate": rate,
        "target_chars": round(rate * duration / 60) if rate else None,
        "analysis_summary": _summary(analysis) if analysis else "",
    }


def _summary(a: dict[str, Any]) -> str:
    lines = [f"- 参考動画の本数: {a['n']} 本"]
    if a["duration_avg"]:
        lines.append(f"- 平均の長さ: {a['duration_avg']} 秒")
    if a["speech_rate_avg"]:
        lines.append(f"- 話す速さ: 平均 1 分あたり {a['speech_rate_avg']} 文字")
    hooks = [o["hooks"][3] for o in a["ones"] if o["hooks"][3]]
    if hooks:
        lines.append("- 最初の 3 秒の発言: " + " / ".join(f"「{h[:30]}」" for h in hooks[:5]))
    ends = [o["ending"] for o in a["ones"] if o["ending"]]
    if ends:
        lines.append("- 最後の 5 秒の発言: " + " / ".join(f"「{e[:30]}」" for e in ends[:5]))
    if a["top_words"]:
        lines.append("- よく使われる言葉: " + "、".join(w for w, _, _ in a["top_words"][:15]))
    cats: dict[str, list[str]] = {}
    for h in a["hits"]:
        cats.setdefault(h["category"], []).append(h["word"])
    for c, ws in cats.items():
        lines.append(f"- {c}の言葉: " + "、".join(ws[:6]))
    return "\n".join(lines)


def skeleton_table(s: dict[str, Any]) -> list[list[str]]:
    return [[r["time"], r["part"], r["elements"], r["phrases"], r["reference"]] for r in s["rows"]]


SKELETON_HEADERS = ["秒数", "パート", "入れる要素", "参考フレーズ", "参考動画の該当部分"]


def claude_prompt(s: dict[str, Any]) -> str:
    """claude.ai に貼る依頼文（C-05b）。"""
    kind_name = "お店の集客用（店舗 SNS）" if s["kind"] == "shop" else "一般"
    table = "| " + " | ".join(SKELETON_HEADERS) + " |\n|" + "---|" * len(SKELETON_HEADERS) + "\n"
    table += "\n".join("| " + " | ".join(c.replace("|", "／") for c in row) + " |" for row in skeleton_table(s))
    out = [
        "TikTok 動画の台本を作ってください。",
        "",
        "## 作りたい動画",
        f"- 内容: {s['intent'] or '（未記入）'}",
        f"- 長さ: {s['duration']:g} 秒",
        f"- 種類: {kind_name}",
    ]
    if s.get("mood"):
        out.append(f"- 雰囲気: {s['mood']}")
    if s.get("target_chars"):
        out.append(f"- 話す量の目安: 約 {s['target_chars']} 文字（参考動画の平均の話す速さから計算）")
    if s["kind"] == "shop" and s.get("shop"):
        out += ["", "## お店の情報"]
        out += [f"- {lbl}: {s['shop'][k]}" for k, lbl in SHOP_FIELDS if s["shop"].get(k)]
    out += ["", "## 構成の骨組み（この流れと秒数に沿ってください）", table]
    if s.get("analysis_summary"):
        out += ["", "## 参考にした動画の分析結果", s["analysis_summary"]]
    out += [
        "",
        "## 注意",
        "- 参考動画の言い回しはそのまま使わず、「型」だけを参考にして新しい言葉で書いてください。",
        "- 事実でないことや大げさな表現（「絶対」「必ず」など）は避けてください。",
        "- 書いていない情報（価格・特典など）は作らず、【要確認】と書いてください。",
        "",
        "## 出力の形",
        "次の列の表で出してください: 秒数 / パート / 話すセリフ / 画面に映すもの・テロップ案",
        "表のあとに、つかみの別案を 3 つ出してください。",
    ]
    return "\n".join(out)
