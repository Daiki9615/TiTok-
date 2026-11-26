"""知見（マーケティングのナレッジ）。最初から入っている知見は knowledge_seed/*.md から読み込む。"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from .storage import DataStore

SEED_DIR = Path(__file__).parent / "knowledge_seed"
FIELDS = ("title", "source", "url", "tags", "added")


def parse_md(text: str) -> dict[str, Any]:
    """先頭の --- で囲んだ項目（title: など）と本文に分ける。"""
    meta: dict[str, Any] = {k: "" for k in FIELDS}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip() in FIELDS:
                    meta[k.strip()] = v.strip()
        body = m.group(2)
    meta["tags"] = [t.strip() for t in re.split(r"[、,，]", meta["tags"] or "") if t.strip()]
    meta["body"] = body.strip()
    return meta


def section(body: str, heading: str) -> str:
    """本文から「## 見出し」の部分だけを取り出す。"""
    m = re.search(rf"^##\s*{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)", body, re.S | re.M)
    return m.group(1).strip() if m else ""


def seed(store: DataStore) -> int:
    """最初から入っている知見を追加する（削除した知見や、自分で直した知見は上書きしない）。"""
    done = set(store.load_setting("knowledge_seeded", []))
    added = 0
    for p in sorted(SEED_DIR.glob("*.md")):
        kid = "seed-" + p.stem
        if kid in done:
            continue
        rec = parse_md(p.read_text(encoding="utf-8"))
        rec["id"] = kid
        store.save_knowledge(rec)
        done.add(kid)
        added += 1
    store.save_setting("knowledge_seeded", sorted(done))
    return added


def new_record(title: str, source: str, url: str, tags: str, body: str, kid: str | None = None) -> dict[str, Any]:
    return {
        "id": kid,
        "title": title.strip() or "（無題）",
        "source": source.strip(),
        "url": url.strip(),
        "tags": [t.strip() for t in re.split(r"[、,，]", tags or "") if t.strip()],
        "added": date.today().isoformat(),
        "body": body.strip(),
    }


def to_markdown(rec: dict[str, Any]) -> str:
    head = [f"# {rec.get('title')}"]
    info = []
    if rec.get("source"):
        info.append(f"出典: {rec['source']}")
    if rec.get("url"):
        info.append(f"URL: {rec['url']}")
    if rec.get("tags"):
        info.append("タグ: " + "、".join(rec["tags"]))
    if rec.get("added"):
        info.append(f"追加日: {rec['added']}")
    if info:
        head.append("  \n".join(info))
    return "\n\n".join(head + [rec.get("body") or ""])


def prompt_digest(recs: list[dict[str, Any]]) -> str:
    """Claude 用依頼文に入れる短いまとめ（ひと言＋動画づくりの使い方）。"""
    out = []
    for r in recs:
        b = r.get("body") or ""
        parts = [f"### {r.get('title')}"]
        one = section(b, "ひと言で")
        use = section(b, "動画づくりに使うなら") or section(b, "動画づくりに使うなら（チェック）")
        if one:
            parts.append(one)
        if use:
            parts.append(use)
        if len(parts) == 1:
            parts.append(b[:600])
        out.append("\n".join(parts))
    return "\n\n".join(out)
