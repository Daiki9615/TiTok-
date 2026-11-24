"""取り込み処理の流れ: URL 確認 → 情報取得 → 重複確認 → 音声取得 → 文字起こし → 保存 → 音声削除。"""
from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .fetcher import meta_from_info
from .storage import DataStore
from .urls import parse_many


@dataclass
class ItemResult:
    url: str
    status: str  # "ok" | "skip" | "error"
    message: str
    video_id: str | None = None


@dataclass
class RunReport:
    items: list[ItemResult] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i.status == status)


def run_import(
    text: str,
    store: DataStore,
    fetcher,
    transcriber,
    kind: str = "general",
    labels: list[str] | None = None,
    force: bool = False,
    interval_sec: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[tuple[str, RunReport]]:
    """1 本ずつ処理し、進み具合（メッセージ, ここまでの結果）を順に返す。失敗しても残りは続ける。"""
    report = RunReport()
    valid, invalid = parse_many(text)
    for p in invalid:
        report.items.append(ItemResult(p.raw, "skip", p.error or "無効な URL"))
    total = len(valid)
    if total == 0:
        yield ("処理できる URL がありません", report)
        return

    for n, p in enumerate(valid, 1):
        head = f"{n}/{total} 本目"
        if p.video_id and store.has_video(p.video_id) and not force:
            report.items.append(ItemResult(p.url, "skip", "保存済み（再処理する場合は「保存済みも再処理」をオン）", p.video_id))
            yield (f"{head}: 保存済みのためスキップ", report)
            continue
        workdir = Path(tempfile.mkdtemp(prefix="tiktok_"))
        try:
            yield (f"{head}: 動画情報を取得中…", report)
            info = fetcher.get_info(p.url, workdir)
            meta = meta_from_info(info)
            if store.has_video(meta["id"]) and not force:
                report.items.append(ItemResult(p.url, "skip", "保存済み", meta["id"]))
                yield (f"{head}: 保存済みのためスキップ", report)
                continue
            yield (f"{head}: 音声を取得中…", report)
            audio = fetcher.download(info, workdir)
            yield (f"{head}: 文字起こし中…（{transcriber.name}）", report)
            tr = transcriber.transcribe(audio)
            if not meta.get("duration"):
                meta["duration"] = tr.get("audio_duration")
            old = store.get_video(meta["id"]) if store.has_video(meta["id"]) else {}
            rec = {
                **meta,
                "kind": kind or old.get("kind", "general"),
                "labels": sorted(set((old.get("labels") or []) + (labels or []))),
                "transcript": tr,
                "edited": False,
            }
            store.save_video(rec)
            report.items.append(ItemResult(p.url, "ok", f"完了（{len(tr['text'])} 文字）", meta["id"]))
            yield (f"{head}: 完了", report)
        except Exception as e:  # 1 本の失敗で全体を止めない
            report.items.append(ItemResult(p.url, "error", f"失敗: {type(e).__name__}: {e}"))
            yield (f"{head}: 失敗", report)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # 音声は必ず削除
        if n < total and interval_sec > 0:
            sleep(interval_sec)

    yield (
        f"終了: 成功 {report.count('ok')} 本 / スキップ {report.count('skip')} 本 / 失敗 {report.count('error')} 本",
        report,
    )
