from pathlib import Path

import pytest

from tiktok_tool import analyzer, exporter, structure
from tiktok_tool.dictionary import DEFAULT_DICTIONARY, dictionary_to_text, text_to_dictionary
from tiktok_tool.fetcher import meta_from_info
from tiktok_tool.pipeline import run_import
from tiktok_tool.storage import DataStore
from tiktok_tool.urls import parse_many, parse_url


def make_rec(vid="111", kind="general", views=1000, segs=None, duration=20, uploader="cafe_a", labels=None):
    segs = segs or [
        {"start": 0.0, "end": 2.5, "text": "駅から徒歩3分の隠れ家カフェ", "words": []},
        {"start": 2.5, "end": 10.0, "text": "看板メニューのパンケーキが本当にふわふわです", "words": []},
        {"start": 10.0, "end": 16.0, "text": "この動画見たでドリンクサービスします", "words": []},
        {"start": 16.0, "end": 20.0, "text": "予約はDMからどうぞフォローしてね", "words": []},
    ]
    return {
        "id": vid, "url": f"https://www.tiktok.com/@x/video/{vid}", "kind": kind, "labels": labels or [],
        "uploader": uploader, "upload_date": "2026-11-01", "caption": "#カフェ PR", "duration": duration,
        "view_count": views, "like_count": views // 10, "comment_count": 3,
        "transcript": {"text": "".join(s["text"] for s in segs), "segments": segs, "model": "fake"},
    }


# ---------- URL ----------
@pytest.mark.parametrize(
    "u,vid",
    [
        ("https://www.tiktok.com/@user.name/video/7300000000000000001?is_from_webapp=1", "7300000000000000001"),
        ("tiktok.com/@a/video/123", "123"),
        ("https://m.tiktok.com/v/456.html", "456"),
    ],
)
def test_parse_video_url(u, vid):
    assert parse_url(u).video_id == vid


def test_parse_short_and_invalid():
    assert parse_url("https://vt.tiktok.com/ZSabc123/").url == "https://vt.tiktok.com/ZSabc123"
    assert parse_url("https://vm.tiktok.com/ZMxyz/").video_id is None
    assert parse_url("https://www.youtube.com/watch?v=1").url is None


def test_parse_many_dedup():
    v, inv = parse_many("https://www.tiktok.com/@a/video/1\nhttps://www.tiktok.com/@a/video/1?x=2\n\nfoo")
    assert len(v) == 1 and len(inv) == 2


# ---------- 取得情報 ----------
def test_meta_from_info():
    m = meta_from_info({"id": "9", "webpage_url": "u", "description": "朝ごはん #カフェ #ランチ", "upload_date": "20261101",
                        "uploader": "a", "duration": 31, "view_count": 5})
    assert m["hashtags"] == ["カフェ", "ランチ"] and m["upload_date"] == "2026-11-01"


# ---------- 取り込み ----------
class FakeFetcher:
    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)

    def get_info(self, url, workdir):
        vid = url.rstrip("/").split("/")[-1]
        if vid in self.fail_ids:
            raise RuntimeError("blocked")
        return {"id": vid, "webpage_url": url, "description": "#test", "duration": 20, "view_count": 10}

    def download(self, info, workdir):
        p = Path(workdir) / f"{info['id']}.m4a"
        p.write_bytes(b"x")
        self.last = p
        return p


class FakeASR:
    name = "fake"

    def transcribe(self, path):
        segs = make_rec()["transcript"]["segments"]
        return {"text": "".join(s["text"] for s in segs), "segments": segs, "audio_duration": 20.0, "model": "fake"}


def test_run_import(tmp_path):
    store = DataStore(tmp_path)
    f = FakeFetcher(fail_ids={"3"})
    text = "\n".join(f"https://www.tiktok.com/@a/video/{i}" for i in (1, 2, 3)) + "\nhttps://example.com"
    steps = list(run_import(text, store, f, FakeASR(), kind="shop", labels=["カフェ"], sleep=lambda s: None))
    rep = steps[-1][1]
    assert (rep.count("ok"), rep.count("error"), rep.count("skip")) == (2, 1, 1)
    assert store.get_video("1")["kind"] == "shop" and store.get_video("1")["labels"] == ["カフェ"]
    assert not f.last.exists()  # 音声は削除される
    # 2 回目は保存済みとしてスキップ
    rep2 = list(run_import("https://www.tiktok.com/@a/video/1", store, f, FakeASR(), sleep=lambda s: None))[-1][1]
    assert rep2.count("skip") == 1


# ---------- 保存 ----------
def test_store_filter(tmp_path):
    s = DataStore(tmp_path)
    s.save_video(make_rec("1", kind="shop", labels=["A"]))
    s.save_video(make_rec("2", uploader="other"))
    assert [r["id"] for r in s.filter_videos(kind="shop")] == ["1"]
    assert [r["id"] for r in s.filter_videos(uploader="oth")] == ["2"]
    assert len(s.filter_videos(keyword="パンケーキ")) == 2
    assert s.all_labels() == ["A"]
    with pytest.raises(ValueError):
        s.get_video("../x")


# ---------- 書き出し・手修正 ----------
def test_srt_and_edit():
    r = make_rec()
    srt = exporter.to_srt(r)
    assert "00:00:02,500 --> 00:00:10,000" in srt
    segs = r["transcript"]["segments"]
    t = exporter.segments_to_edit_text(segs).replace("パンケーキ", "ホットケーキ")
    new = exporter.apply_edit_text(segs, t)
    assert new[1]["text"].startswith("看板メニューのホットケーキ") and new[1]["start"] == 2.5
    # 行を足した場合は [分:秒] を時刻として使う
    new2 = exporter.apply_edit_text(segs, t + "\n[00:19] おまけ")
    assert len(new2) == 5 and new2[-1]["start"] == 19


# ---------- 辞書 ----------
def test_dictionary_roundtrip():
    d, err = text_to_dictionary(dictionary_to_text(DEFAULT_DICTIONARY))
    assert not err and d == DEFAULT_DICTIONARY
    _, err = text_to_dictionary("これは不正な行")
    assert err


# ---------- 分析 ----------
def test_analyze_one_shop():
    r = make_rec(kind="shop")
    a = analyzer.analyze_one(r, DEFAULT_DICTIONARY)
    assert a["hooks"][3].startswith("駅から徒歩")
    assert "フォロー" in a["ending"]
    cats = {h["category"] for h in a["hits"]}
    assert {"来店誘導", "来店特典", "締め", "PR"} <= cats
    assert a["speech_rate"] > 0
    assert [f["part"] for f in a["flow"]] == ["つかみ", "本題", "締め"]
    # 一般の動画では店舗の分類を数えない
    g = analyzer.analyze_one(make_rec(kind="general"), DEFAULT_DICTIONARY)
    assert "来店誘導" not in {h["category"] for h in g["hits"]}


def test_word_timestamps_used():
    segs = [{"start": 0, "end": 4, "text": "こんにちは予約", "words": [
        {"start": 0.0, "end": 1.0, "word": "こんにちは"}, {"start": 3.5, "end": 4.0, "word": "予約"}]}]
    r = make_rec(kind="shop", segs=segs, duration=4)
    hit = [h for h in analyzer.dictionary_hits(r, DEFAULT_DICTIONARY) if h["word"] == "予約"][0]
    assert hit["first_sec"] == 3.5
    assert analyzer.Timeline(r).between(0, 3) == "こんにちは"


def test_analyze_many_and_compare():
    recs = [make_rec(str(i), kind="shop", views=v, uploader=u) for i, (v, u) in enumerate([(100, "a"), (5000, "b"), (300, "a"), (9000, "b")])]
    a = analyzer.analyze_many(recs, DEFAULT_DICTIONARY)
    assert a["n"] == 4
    assert any(k == 4 for _, k in a["hook_phrases"][3])
    words = {w for w, _, _ in a["top_words"]}
    assert "パンケーキ" in words
    rows = analyzer.compare(recs, "views", DEFAULT_DICTIONARY)
    assert {r["group"] for r in rows} == {"再生数 上位", "再生数 下位"}
    wm = analyzer.word_vs_metrics(recs, "パンケーキ")
    assert wm["with_n"] == 4


# ---------- 構成 ----------
def test_allocate():
    parts = structure.allocate(30, structure.TEMPLATES["general"])
    assert parts[0][1] == 0 and parts[-1][2] == 30
    assert all(a <= b for _, a, b, _ in parts)


def test_build_skeleton_shop_prompt():
    refs = [make_rec("1", kind="shop"), make_rec("2", kind="shop")]
    sk = structure.build_skeleton(refs, DEFAULT_DICTIONARY, "平日ランチのお得さ", 30, "shop", "明るく",
                                  {"name": "カフェ森", "benefit": "ドリンク無料", "place": "渋谷駅 徒歩3分"})
    assert len(sk["rows"]) == 5
    assert "ドリンク無料" in sk["rows"][3]["elements"]
    assert "参考動画A" in sk["rows"][0]["reference"]
    p = structure.claude_prompt(sk)
    assert "カフェ森" in p and "そのまま使わず" in p and "| 秒数 |" in p


def test_build_skeleton_without_refs():
    sk = structure.build_skeleton([], DEFAULT_DICTIONARY, "朝の時短", 15)
    assert sk["target_chars"] is None and len(sk["rows"]) == 5
    assert "朝の時短" in structure.claude_prompt(sk)


# ---------- 画面 ----------
def test_app_builds(tmp_path):
    from tiktok_tool.app import App

    s = DataStore(tmp_path)
    s.save_video(make_rec("1", kind="shop"))
    app = App(s)
    app.build()
    md, chart, words, hits, per, path = app.run_analysis(["1"])
    assert "構成の流れ" in md and Path(path).exists()
    df, prompt, sk = app.build_structure(["1"], "テスト", 30, "shop", "", *[""] * len(structure.SHOP_FIELDS))
    msg, _, sid = app.save_structure(sk, df, prompt, "案1", "", None)
    assert sid and app.store.get_structure(sid)["title"] == "案1"
    assert "保存しました" in app.save_edit("1", app.show_video("1")[1].replace("パンケーキ", "ワッフル"), "shop", "A、B")
    assert app.store.get_video("1")["labels"] == ["A", "B"] and app.store.get_video("1")["edited"]


def test_sheets_mirror(tmp_path):
    from tiktok_tool.storage import SheetsMirror

    class WS:
        def clear(self): self.rows = None
        def update(self, rows, rng): self.rows = rows

    class SS:
        sheet1 = WS(); url = "https://docs.google.com/x"

    class GC:
        def open(self, name): return SS()

    m = SheetsMirror(GC())
    long = make_rec("9", segs=[{"start": 0, "end": 1, "text": "あ" * 60000, "words": []}])
    assert m.sync([make_rec("1"), long]) == 2
    rows = SS.sheet1.rows
    assert rows[0][0] == "動画ID" and len(rows[2][14]) < 50000 and m.url
