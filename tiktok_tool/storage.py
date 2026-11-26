"""保存（D-01〜D-05）。Google ドライブ上のフォルダに 1 動画 1 ファイル（JSON）で保存する。
スプレッドシートへの一覧の書き出しは SheetsMirror（任意）で行う。"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

VIDEO_KINDS = {"general": "一般", "shop": "店舗SNS"}


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class DataStore:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.videos_dir = self.base / "videos"
        self.structures_dir = self.base / "structures"
        self.settings_dir = self.base / "settings"
        self.knowledge_dir = self.base / "knowledge"
        for d in (self.videos_dir, self.structures_dir, self.settings_dir, self.knowledge_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 動画 ----
    def _vpath(self, vid: str) -> Path:
        if not re.fullmatch(r"[\w\-]+", vid):
            raise ValueError(f"不正な動画 ID: {vid}")
        return self.videos_dir / f"{vid}.json"

    def has_video(self, vid: str) -> bool:
        return self._vpath(vid).exists()

    def save_video(self, rec: dict[str, Any]) -> None:
        rec.setdefault("kind", "general")
        rec.setdefault("labels", [])
        rec["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _atomic_write(self._vpath(rec["id"]), rec)

    def get_video(self, vid: str) -> dict[str, Any]:
        return json.loads(self._vpath(vid).read_text(encoding="utf-8"))

    def delete_video(self, vid: str) -> None:
        self._vpath(vid).unlink(missing_ok=True)

    def list_videos(self) -> list[dict[str, Any]]:
        out = []
        for p in self.videos_dir.glob("*.json"):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        out.sort(key=lambda r: (r.get("upload_date") or "", r.get("id")), reverse=True)
        return out

    def filter_videos(
        self,
        kind: str | None = None,
        label: str | None = None,
        uploader: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        res = []
        for r in self.list_videos():
            if kind and r.get("kind") != kind:
                continue
            if label and label not in (r.get("labels") or []):
                continue
            if uploader and uploader.lower() not in (
                (r.get("uploader") or "") + " " + (r.get("uploader_id") or "")
            ).lower():
                continue
            if keyword:
                hay = (r.get("transcript", {}).get("text") or "") + (r.get("caption") or "")
                if keyword not in hay:
                    continue
            res.append(r)
        return res

    def all_labels(self) -> list[str]:
        s: set[str] = set()
        for r in self.list_videos():
            s.update(r.get("labels") or [])
        return sorted(s)

    # ---- 構成案 ----
    def save_structure(self, rec: dict[str, Any]) -> str:
        sid = rec.get("id") or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        rec["id"] = sid
        rec["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _atomic_write(self.structures_dir / f"{sid}.json", rec)
        return sid

    def get_structure(self, sid: str) -> dict[str, Any]:
        if not re.fullmatch(r"[\w\-]+", sid):
            raise ValueError("不正な ID")
        return json.loads((self.structures_dir / f"{sid}.json").read_text(encoding="utf-8"))

    def list_structures(self) -> list[dict[str, Any]]:
        out = []
        for p in self.structures_dir.glob("*.json"):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return out

    # ---- 知見 ----
    def save_knowledge(self, rec: dict[str, Any]) -> str:
        kid = rec.get("id") or "k-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        if not re.fullmatch(r"[\w\-]+", kid):
            raise ValueError("不正な ID")
        rec["id"] = kid
        rec["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _atomic_write(self.knowledge_dir / f"{kid}.json", rec)
        return kid

    def get_knowledge(self, kid: str) -> dict[str, Any]:
        if not re.fullmatch(r"[\w\-]+", kid):
            raise ValueError("不正な ID")
        return json.loads((self.knowledge_dir / f"{kid}.json").read_text(encoding="utf-8"))

    def delete_knowledge(self, kid: str) -> None:
        if re.fullmatch(r"[\w\-]+", kid):
            (self.knowledge_dir / f"{kid}.json").unlink(missing_ok=True)

    def list_knowledge(self) -> list[dict[str, Any]]:
        out = []
        for p in self.knowledge_dir.glob("*.json"):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        out.sort(key=lambda r: (r.get("added") or "", r.get("id")), reverse=True)
        return out

    # ---- 設定 ----
    def load_setting(self, name: str, default: Any) -> Any:
        p = self.settings_dir / f"{name}.json"
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def save_setting(self, name: str, value: Any) -> None:
        _atomic_write(self.settings_dir / f"{name}.json", value)


# Google スプレッドシートの 1 セルの文字数上限（50,000 文字）より少し小さく切る
_CELL_LIMIT = 49000

SHEET_HEADERS = [
    "動画ID", "URL", "種類", "ラベル", "投稿者", "投稿者ID", "投稿日", "長さ(秒)",
    "再生数", "いいね数", "コメント数", "シェア数", "キャプション", "ハッシュタグ",
    "文字起こし", "取得日時", "音声認識モデル",
]


def video_to_row(r: dict[str, Any]) -> list[Any]:
    text = r.get("transcript", {}).get("text") or ""
    if len(text) > _CELL_LIMIT:
        text = text[:_CELL_LIMIT] + "…（続きはツール上で確認）"
    return [
        r.get("id"), r.get("url"), VIDEO_KINDS.get(r.get("kind"), r.get("kind")),
        "、".join(r.get("labels") or []), r.get("uploader"), r.get("uploader_id"),
        r.get("upload_date"), r.get("duration"), r.get("view_count"), r.get("like_count"),
        r.get("comment_count"), r.get("repost_count"), r.get("caption"),
        " ".join("#" + t for t in r.get("hashtags") or []), text, r.get("fetched_at"),
        r.get("transcript", {}).get("model"),
    ]


class SheetsMirror:
    """保存済みの動画一覧を Google スプレッドシートに書き出す（gspread のクライアントを渡す）。"""

    def __init__(self, gspread_client, spreadsheet_name: str = "TikTok文字起こしデータ"):
        self.gc = gspread_client
        self.name = spreadsheet_name
        self._ss = None

    def _sheet(self):
        import gspread

        if self._ss is None:
            try:
                self._ss = self.gc.open(self.name)
            except gspread.SpreadsheetNotFound:
                self._ss = self.gc.create(self.name)
        return self._ss.sheet1

    @property
    def url(self) -> str | None:
        return self._ss.url if self._ss is not None else None

    def sync(self, videos: Iterable[dict[str, Any]]) -> int:
        rows = [SHEET_HEADERS] + [["" if v is None else v for v in video_to_row(r)] for r in videos]
        ws = self._sheet()
        ws.clear()
        ws.update(rows, "A1")
        return len(rows) - 1
