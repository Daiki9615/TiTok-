"""辞書（分析で数える言葉の一覧）。「共通」はすべての動画、「店舗」は店舗 SNS の動画で使う。"""
from __future__ import annotations

import re
from typing import Any

SCOPES = {"common": "共通", "shop": "店舗"}
_SCOPE_REV = {v: k for k, v in SCOPES.items()}

DEFAULT_DICTIONARY: dict[str, dict[str, Any]] = {
    "誘導": {"scope": "common", "words": ["プロフのリンク", "プロフィール", "プロフ", "概要欄", "リンク", "詳細は", "コメント欄"]},
    "期限・限定": {"scope": "common", "words": ["今だけ", "期間限定", "限定", "セール", "本日まで", "残りわずか"]},
    "お得感": {"scope": "common", "words": ["円", "%オフ", "半額", "コスパ", "無料", "お得"]},
    "悩み・共感": {"scope": "common", "words": ["悩んでる", "困ってる", "な人", "私も", "あるある", "わかる"]},
    "評価・強調": {"scope": "common", "words": ["神", "優勝", "リピ", "買ってよかった", "本当に", "マジで", "絶対"]},
    "締め": {"scope": "common", "words": ["フォロー", "保存", "いいね", "コメント", "シェア", "また見て"]},
    "PR": {"scope": "common", "words": ["PR", "広告", "プロモーション", "提供"]},
    "来店誘導": {"scope": "shop", "words": ["予約", "DM", "Googleマップ", "マップ", "駅", "徒歩", "営業時間", "定休日", "テイクアウト", "場所は"]},
    "来店特典": {"scope": "shop", "words": ["この動画見た", "動画見た", "初回", "サービス", "プレゼント", "特典", "クーポン"]},
    "見せ方（店名・場所）": {"scope": "shop", "words": ["店名", "お店", "店", "駅", "通り", "エリア"]},
    "見せ方（商品・メニュー）": {"scope": "shop", "words": ["メニュー", "看板", "人気", "おすすめ", "新作", "限定メニュー", "ランチ", "セット"]},
    "見せ方（人）": {"scope": "shop", "words": ["スタッフ", "店長", "オーナー", "大将", "職人", "店員"]},
    "見せ方（雰囲気）": {"scope": "shop", "words": ["雰囲気", "おしゃれ", "落ち着く", "隠れ家", "映え", "内装", "BGM"]},
}


def dictionary_to_text(d: dict[str, dict[str, Any]]) -> str:
    lines = []
    for name, v in d.items():
        lines.append(f"[{SCOPES.get(v.get('scope'), '共通')}] {name}: {'、'.join(v.get('words') or [])}")
    return "\n".join(lines)


_LINE = re.compile(r"^\s*(?:\[(共通|店舗)\]\s*)?([^:：]+?)\s*[:：]\s*(.*)$")


def text_to_dictionary(text: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """画面で編集した文字を辞書に戻す。読めなかった行はエラーとして返す。"""
    d: dict[str, dict[str, Any]] = {}
    errors = []
    for i, line in enumerate((text or "").splitlines(), 1):
        if not line.strip():
            continue
        m = _LINE.match(line)
        if not m:
            errors.append(f"{i} 行目を読めません（「[共通] 分類名: 言葉1、言葉2」の形で書いてください）: {line}")
            continue
        scope = _SCOPE_REV.get(m.group(1) or "共通", "common")
        words = [w.strip() for w in re.split(r"[、,，]", m.group(3)) if w.strip()]
        name = m.group(2).strip()
        if name in d:
            d[name]["words"] += [w for w in words if w not in d[name]["words"]]
        else:
            d[name] = {"scope": scope, "words": words}
    return d, errors


def categories_for(d: dict[str, dict[str, Any]], kind: str) -> dict[str, list[str]]:
    """動画の種類に合う分類だけを返す（店舗の分類は店舗 SNS の動画のときだけ）。"""
    return {
        name: v["words"]
        for name, v in d.items()
        if v.get("scope", "common") == "common" or (v.get("scope") == "shop" and kind == "shop")
    }
