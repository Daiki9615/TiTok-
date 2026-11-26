"""ブラウザ画面（Gradio）。①取り込み ②一覧・閲覧 ③分析 ④構成作成 ⑤辞書設定。"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr
import pandas as pd

from . import analyzer, exporter, structure
from . import knowledge
from .dictionary import DEFAULT_DICTIONARY, dictionary_to_text, text_to_dictionary
from .exporter import fmt_ts
from .pipeline import run_import
from .storage import VIDEO_KINDS, DataStore

KIND_CHOICES = [("一般", "general"), ("店舗SNS", "shop")]
FILTER_KIND_CHOICES = [("すべて", "")] + KIND_CHOICES


def _labels(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[、,，\n]", text or "") if t.strip()]


def _choice_label(r: dict[str, Any]) -> str:
    cap = (r.get("caption") or "").replace("\n", " ")
    return f"{r.get('upload_date') or '----'} | {r.get('uploader') or '?'} | {cap[:24]} ({r['id']})"


def _num(v: Any) -> str:
    return "" if v is None else f"{int(v):,}" if isinstance(v, (int, float)) else str(v)


class App:
    def __init__(self, store: DataStore, fetcher=None, transcriber=None, sheets=None):
        self.store = store
        self.fetcher = fetcher
        self.transcriber = transcriber
        self.sheets = sheets
        self.tmp = Path(tempfile.mkdtemp(prefix="tiktok_export_"))
        knowledge.seed(store)

    # ---------- 共通 ----------
    @property
    def dictionary(self) -> dict:
        return self.store.load_setting("dictionary", DEFAULT_DICTIONARY)

    def _write(self, name: str, text: str) -> str:
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def _filtered(self, kind, label, uploader, keyword):
        return self.store.filter_videos(kind or None, label or None, uploader or None, keyword or None)

    def video_choices(self, kind="", label="", uploader="", keyword=""):
        return [(_choice_label(r), r["id"]) for r in self._filtered(kind, label, uploader, keyword)]

    def _sync_sheets(self) -> str:
        if not self.sheets:
            return ""
        try:
            n = self.sheets.sync(self.store.list_videos())
            return f"スプレッドシートに {n} 本を書き出しました: {self.sheets.url}"
        except Exception as e:
            return f"スプレッドシートへの書き出しに失敗しました（データはドライブに保存済み）: {e}"

    # ---------- ① 取り込み ----------
    def do_import(self, urls, kind, labels, force):
        if not self.fetcher or not self.transcriber:
            yield "この環境では取り込みを使えません（Colab のノートから起動してください）", None
            return
        log: list[str] = []
        report = None
        for msg, report in run_import(urls, self.store, self.fetcher, self.transcriber, kind, _labels(labels), force):
            log.append(msg)
            yield "\n".join(log[-15:]), self._report_df(report)
        if report and report.count("ok"):
            s = self._sync_sheets()
            if s:
                log.append(s)
        yield "\n".join(log[-15:]), self._report_df(report) if report else None

    @staticmethod
    def _report_df(report):
        mark = {"ok": "✅ 成功", "skip": "⏭ スキップ", "error": "❌ 失敗"}
        return pd.DataFrame(
            [[mark[i.status], i.url, i.message, i.video_id or ""] for i in report.items],
            columns=["結果", "URL", "内容", "動画ID"],
        )

    # ---------- ② 一覧・閲覧 ----------
    def list_table(self, kind, label, uploader, keyword):
        rows = []
        for r in self._filtered(kind, label, uploader, keyword):
            rows.append(
                [
                    r.get("upload_date"), r.get("uploader"), VIDEO_KINDS.get(r.get("kind"), ""),
                    "、".join(r.get("labels") or []), r.get("duration"), _num(r.get("view_count")),
                    _num(r.get("like_count")), (r.get("caption") or "")[:40], r["id"],
                ]
            )
        df = pd.DataFrame(rows, columns=["投稿日", "投稿者", "種類", "ラベル", "長さ(秒)", "再生数", "いいね", "キャプション", "動画ID"])
        choices = self.video_choices(kind, label, uploader, keyword)
        return df, gr.update(choices=choices, value=None), f"{len(rows)} 本"

    def show_video(self, vid):
        if not vid:
            return "", "", "general", "", None
        r = self.store.get_video(vid)
        info = (
            f"**{r.get('uploader')}**（{r.get('uploader_id')}） ・ 投稿日 {r.get('upload_date')} ・ 長さ {r.get('duration')} 秒\n\n"
            f"再生 {_num(r.get('view_count'))} ・ いいね {_num(r.get('like_count'))} ・ コメント {_num(r.get('comment_count'))} ・ シェア {_num(r.get('repost_count'))}"
            f"（{r.get('fetched_at')} 時点）\n\n"
            f"URL: {r.get('url')}\n\nキャプション: {r.get('caption')}\n\n"
            f"音声認識: {r.get('transcript', {}).get('model')}{' ・ 手修正あり' if r.get('edited') else ''}"
        )
        text = exporter.segments_to_edit_text(r.get("transcript", {}).get("segments") or [])
        return info, text, r.get("kind", "general"), "、".join(r.get("labels") or []), None

    def save_edit(self, vid, text, kind, labels):
        if not vid:
            return "動画を選んでください"
        r = self.store.get_video(vid)
        old = r.get("transcript", {}).get("segments") or []
        new = exporter.apply_edit_text(old, text)
        if new != old:
            r["transcript"]["segments"] = new
            r["transcript"]["text"] = "".join(s["text"] for s in new)
            r["edited"] = True
        r["kind"] = kind
        r["labels"] = _labels(labels)
        self.store.save_video(r)
        s = self._sync_sheets()
        return "保存しました" + (f"\n{s}" if s else "")

    def export_video(self, vid, fmt):
        if not vid:
            return None
        r = self.store.get_video(vid)
        if fmt == "srt":
            return self._write(f"{vid}.srt", exporter.to_srt(r))
        return self._write(f"{vid}.txt", exporter.to_txt(r, timestamps=(fmt == "txt_ts")))

    def export_list(self, kind, label, uploader, keyword):
        return self._write("videos.csv", exporter.videos_csv(self._filtered(kind, label, uploader, keyword)))

    def delete_video(self, vid, confirm):
        if not vid:
            return "動画を選んでください"
        if not confirm:
            return "削除する場合は「本当に削除する」にチェックを入れてください"
        self.store.delete_video(vid)
        s = self._sync_sheets()
        return "削除しました" + (f"\n{s}" if s else "")

    # ---------- ③ 分析 ----------
    def select_all(self, kind, label, uploader, keyword):
        ch = self.video_choices(kind, label, uploader, keyword)
        return gr.update(choices=ch, value=[v for _, v in ch])

    def run_analysis(self, ids):
        empty = pd.DataFrame()
        if not ids:
            return "動画を 1 本以上選んでください", empty, empty, empty, empty, None
        recs = [self.store.get_video(i) for i in ids]
        d = self.dictionary
        a = analyzer.analyze_many(recs, d)
        md = [f"### 分析した動画: {a['n']} 本"]
        if a["speech_rate_avg"]:
            md.append(
                f"- 話す速さ: 平均 **1 分あたり {a['speech_rate_avg']} 文字**"
                + (f"（最小 {a['speech_rate_min']} 〜 最大 {a['speech_rate_max']}）" if a["n"] > 1 else "")
            )
        if a["duration_avg"]:
            md.append(f"- 長さ: 平均 {a['duration_avg']} 秒")
        if a["duration_views_corr"] is not None:
            md.append(f"- 長さと再生数の関係（相関係数 −1〜1）: {a['duration_views_corr']}（3 本以上で計算。本数が少ないと当てにならない）")
        if a["n"] == 1:
            md.append("\n### 構成の流れ")
            for f in a["ones"][0]["flow"]:
                md.append(f"- **{f['part']}**（{f['start']}〜{f['end']} 秒）: {f['text'] or '（発言なし）'}")
        else:
            for s in analyzer.HOOK_SECONDS:
                ph = a["hook_phrases"][s]
                md.append(f"\n**最初の {s} 秒によく出る言い回し**: " + ("、".join(f"{p}（{k}本）" for p, k in ph) or "2 本以上で共通するものなし"))
            ph = a["ending_phrases"]
            md.append(f"\n**最後の {analyzer.ENDING_SECONDS} 秒によく出る言い回し**: " + ("、".join(f"{p}（{k}本）" for p, k in ph) or "2 本以上で共通するものなし"))

        words = pd.DataFrame(a["top_words"], columns=["言葉", "回数", "出てきた動画の本数"])
        hits = pd.DataFrame(
            [[h["category"], h["word"], h["videos"], h["count"], h["avg_first_sec"]] for h in a["hits"]],
            columns=["分類", "言葉", "出てきた動画の本数", "合計回数", "最初に出る平均秒数"],
        )
        per = pd.DataFrame(
            [
                [
                    r.get("uploader"), r.get("upload_date"), o["duration"], o["speech_rate"],
                    o["hooks"][3], o["hooks"][5], o["ending"], _num(r.get("view_count")), r["id"],
                ]
                for o, r in zip(a["ones"], recs)
            ],
            columns=["投稿者", "投稿日", "長さ(秒)", "話す速さ(字/分)", "最初の3秒", "最初の5秒", "最後の5秒", "再生数", "動画ID"],
        )
        top = words.head(15)[["言葉", "回数"]]
        ymax = int(top["回数"].max()) if not top.empty else 1
        chart = gr.BarPlot(value=top, x="言葉", y="回数", sort="-y", y_lim=[0, ymax + 1], label="よく使われる言葉（上位 15）")
        csv_path = self._write(
            "analysis.csv",
            exporter.rows_csv(list(per.columns), per.values.tolist())
            + "\n"
            + exporter.rows_csv(list(words.columns), words.values.tolist())
            + "\n"
            + exporter.rows_csv(list(hits.columns), hits.values.tolist()),
        )
        return "\n".join(md), chart, words, hits, per, csv_path

    def run_compare(self, ids, by):
        if not ids:
            return pd.DataFrame()
        recs = [self.store.get_video(i) for i in ids]
        rows = analyzer.compare(recs, by, self.dictionary)
        return pd.DataFrame(
            [[r["group"], r["n"], _num(r["avg_views"]), r["speech_rate"], r["avg_duration"], r["top_words"], r["hook_phrases"], r["dictionary"]] for r in rows],
            columns=["グループ", "本数", "平均再生数", "話す速さ(字/分)", "平均の長さ(秒)", "よく使う言葉", "つかみの言い回し", "辞書の分類(本数)"],
        )

    def run_word_metric(self, ids, word):
        if not ids or not word:
            return "動画と言葉を指定してください"
        recs = [self.store.get_video(i) for i in ids]
        r = analyzer.word_vs_metrics(recs, word)
        lines = [f"「{word}」を含む動画: {r['with_n']} 本 / 含まない動画: {r['without_n']} 本", "", "| | 含む | 含まない |", "|---|---|---|"]
        for k in ("再生数", "いいね数", "コメント数"):
            a, b = r[k]
            lines.append(f"| 平均{k} | {_num(a)} | {_num(b)} |")
        lines.append("\n※ 本数が少ないと偶然の差が大きい。数値は取得した時点のもの。")
        return "\n".join(lines)

    # ---------- ④ 構成作成 ----------
    def build_structure(self, ids, intent, duration, kind, mood, kn_ids, *shop_vals):
        refs = [self.store.get_video(i) for i in (ids or [])]
        shop = {k: (v or "").strip() for (k, _), v in zip(structure.SHOP_FIELDS, shop_vals)}
        sk = structure.build_skeleton(refs, self.dictionary, intent or "", float(duration or 30), kind, mood or "", shop)
        df = pd.DataFrame(structure.skeleton_table(sk), columns=structure.SKELETON_HEADERS)
        kns = [self.store.get_knowledge(k) for k in (kn_ids or [])]
        if kns:
            sk["knowledge_ids"] = list(kn_ids)
            sk["knowledge_digest"] = knowledge.prompt_digest(kns)
        return df, structure.claude_prompt(sk), sk

    def save_structure(self, sk, table, prompt, title, script, sid):
        if not sk:
            return "先に「骨組みを作る」を押してください", gr.update(), sid
        rec = dict(sk)
        if isinstance(table, pd.DataFrame) and not table.empty:
            rec["rows"] = [dict(zip(["time", "part", "elements", "phrases", "reference"], map(str, row))) for row in table.values.tolist()]
        rec.update({"title": title or "（無題）", "prompt": prompt, "script": script or "", "id": sid or None})
        new_id = self.store.save_structure(rec)
        return f"保存しました（{rec['title']}）", gr.update(choices=self.structure_choices(), value=new_id), new_id

    def structure_choices(self):
        return [(f"{s.get('updated_at', '')[:16]} | {s.get('title')}", s["id"]) for s in self.store.list_structures()]

    def load_structure(self, sid):
        if not sid:
            return gr.update(), "", "", "", None, None
        s = self.store.get_structure(sid)
        df = pd.DataFrame(structure.skeleton_table(s), columns=structure.SKELETON_HEADERS)
        return df, s.get("prompt", ""), s.get("title", ""), s.get("script", ""), s, sid

    def export_structure(self, table, prompt, title, script):
        lines = [f"# {title or '構成案'}", ""]
        if isinstance(table, pd.DataFrame) and not table.empty:
            lines += [" / ".join(table.columns)] + [" / ".join(map(str, r)) for r in table.values.tolist()]
        if script:
            lines += ["", "## 台本", script]
        lines += ["", "## Claude 用依頼文", prompt or ""]
        return self._write("structure.txt", "\n".join(lines))

    # ---------- ⑥ 知見 ----------
    def knowledge_choices(self, tag=""):
        return [
            (f"{k.get('title')}" + (f"（{'、'.join(k.get('tags') or [])}）" if k.get("tags") else ""), k["id"])
            for k in self.store.list_knowledge()
            if not tag or tag in (k.get("tags") or [])
        ]

    def knowledge_tags(self):
        s: set[str] = set()
        for k in self.store.list_knowledge():
            s.update(k.get("tags") or [])
        return [""] + sorted(s)

    def show_knowledge(self, kid):
        if not kid:
            return "左上から知見を選んでください", "", "", "", "", "", None
        k = self.store.get_knowledge(kid)
        return (
            knowledge.to_markdown(k), k.get("title", ""), k.get("source", ""), k.get("url", ""),
            "、".join(k.get("tags") or []), k.get("body", ""), kid,
        )

    def save_knowledge(self, title, source, url, tags, body, kid):
        if not (title or "").strip() or not (body or "").strip():
            return "タイトルと内容は必ず入れてください", gr.update(), kid
        rec = knowledge.new_record(title, source, url, tags, body, kid)
        if kid:
            rec["added"] = self.store.get_knowledge(kid).get("added") or rec["added"]
        new_id = self.store.save_knowledge(rec)
        return "保存しました", gr.update(choices=self.knowledge_choices(), value=new_id), new_id

    def delete_knowledge(self, kid, confirm):
        if not kid:
            return "知見を選んでください", gr.update(), kid
        if not confirm:
            return "削除する場合は「本当に削除する」にチェックを入れてください", gr.update(), kid
        self.store.delete_knowledge(kid)
        return "削除しました", gr.update(choices=self.knowledge_choices(), value=None), None

    # ---------- ⑤ 辞書 ----------
    def save_dictionary(self, text):
        d, errors = text_to_dictionary(text)
        if errors:
            return "保存していません:\n" + "\n".join(errors)
        self.store.save_setting("dictionary", d)
        return f"保存しました（{len(d)} 分類）"

    def reset_dictionary(self):
        self.store.save_setting("dictionary", DEFAULT_DICTIONARY)
        return dictionary_to_text(DEFAULT_DICTIONARY), "初期値に戻しました"

    # ---------- 画面 ----------
    def _filters(self):
        with gr.Row():
            kind = gr.Dropdown(FILTER_KIND_CHOICES, value="", label="種類")
            label = gr.Dropdown([""] + self.store.all_labels(), value="", label="ラベル", allow_custom_value=True)
            uploader = gr.Textbox(label="投稿者（一部でOK）")
            keyword = gr.Textbox(label="キーワード（文字起こし・キャプション）")
        return [kind, label, uploader, keyword]

    def build(self) -> gr.Blocks:
        with gr.Blocks(title="TikTok 文字起こし・分析") as demo:
            gr.Markdown("# TikTok 文字起こし・分析ツール")
            with gr.Tab("① 取り込み"):
                urls = gr.Textbox(lines=8, label="TikTok の URL（1 行に 1 つ。まとめて貼り付けOK）", placeholder="https://www.tiktok.com/@xxx/video/123...\nhttps://vt.tiktok.com/...")
                with gr.Row():
                    kind = gr.Radio(KIND_CHOICES, value="general", label="動画の種類")
                    labels = gr.Textbox(label="ラベル（読点区切り・任意）", placeholder="例: カフェ、競合A")
                    force = gr.Checkbox(label="保存済みも再処理する", value=False)
                go = gr.Button("文字起こしを開始", variant="primary")
                log = gr.Textbox(label="進み具合", lines=8, interactive=False)
                result = gr.Dataframe(label="結果", interactive=False, wrap=True)
                go.click(self.do_import, [urls, kind, labels, force], [log, result])

            with gr.Tab("② 一覧・閲覧"):
                f2 = self._filters()
                with gr.Row():
                    search = gr.Button("絞り込む", variant="primary")
                    csv_btn = gr.Button("一覧を CSV で書き出す")
                    if self.sheets:
                        sheet_btn = gr.Button("スプレッドシートに書き出す")
                count = gr.Markdown()
                table = gr.Dataframe(interactive=False, wrap=True, max_height=400)
                pick = gr.Dropdown([], label="動画を選ぶ", interactive=True)
                info = gr.Markdown()
                edit = gr.Textbox(label="文字起こし（直接書き換えて「保存」できます。[分:秒] はそのまま残してください）", lines=14)
                with gr.Row():
                    ekind = gr.Radio(KIND_CHOICES, label="種類")
                    elabels = gr.Textbox(label="ラベル（読点区切り）")
                with gr.Row():
                    save = gr.Button("保存", variant="primary")
                    fmt = gr.Radio([("txt（時刻つき）", "txt_ts"), ("txt（全文のみ）", "txt"), ("srt", "srt")], value="txt_ts", label="書き出し形式")
                    dl = gr.Button("この動画を書き出す")
                with gr.Row():
                    confirm = gr.Checkbox(label="本当に削除する")
                    delete = gr.Button("この動画を削除", variant="stop")
                msg2 = gr.Textbox(label="メッセージ", interactive=False)
                file2 = gr.File(label="ダウンロード")
                search.click(self.list_table, f2, [table, pick, count])
                demo.load(self.list_table, f2, [table, pick, count])
                pick.change(self.show_video, pick, [info, edit, ekind, elabels, file2])
                save.click(self.save_edit, [pick, edit, ekind, elabels], msg2)
                dl.click(self.export_video, [pick, fmt], file2)
                csv_btn.click(self.export_list, f2, file2)
                delete.click(self.delete_video, [pick, confirm], msg2).then(self.list_table, f2, [table, pick, count])
                if self.sheets:
                    sheet_btn.click(self._sync_sheets, None, msg2)

            with gr.Tab("③ 分析"):
                f3 = self._filters()
                with gr.Row():
                    refresh3 = gr.Button("一覧を更新")
                    all3 = gr.Button("絞り込んだ動画を全部選ぶ")
                ids3 = gr.Dropdown([], multiselect=True, label="分析する動画（1 本から）")
                run3 = gr.Button("分析する", variant="primary")
                summary = gr.Markdown()
                chart = gr.BarPlot(x="言葉", y="回数", sort="-y", label="よく使われる言葉（上位 15）")
                with gr.Tab("動画ごと"):
                    per = gr.Dataframe(interactive=False, wrap=True)
                with gr.Tab("よく使われる言葉"):
                    words = gr.Dataframe(interactive=False)
                with gr.Tab("辞書の言葉"):
                    hits = gr.Dataframe(interactive=False)
                with gr.Tab("比べる"):
                    by = gr.Radio([(v, k) for k, v in analyzer.GROUP_BY.items()], value="views", label="比べ方")
                    cmp_btn = gr.Button("比べる")
                    cmp = gr.Dataframe(interactive=False, wrap=True)
                with gr.Tab("言葉と再生数"):
                    word = gr.Textbox(label="言葉", placeholder="例: 予約")
                    wm_btn = gr.Button("比べる")
                    wm = gr.Markdown()
                file3 = gr.File(label="分析結果（CSV）")
                refresh3.click(lambda *a: gr.update(choices=self.video_choices(*a)), f3, ids3)
                demo.load(lambda *a: gr.update(choices=self.video_choices(*a)), f3, ids3)
                all3.click(self.select_all, f3, ids3)
                run3.click(self.run_analysis, ids3, [summary, chart, words, hits, per, file3])
                cmp_btn.click(self.run_compare, [ids3, by], cmp)
                wm_btn.click(self.run_word_metric, [ids3, word], wm)

            with gr.Tab("④ 構成作成"):
                sk_state = gr.State(None)
                sid_state = gr.State(None)
                with gr.Row():
                    saved = gr.Dropdown(self.structure_choices(), label="保存した構成案を開く")
                    refresh4 = gr.Button("動画の一覧を更新")
                ids4 = gr.Dropdown([], multiselect=True, label="参考にする動画（1 本以上・任意）")
                kn4 = gr.Dropdown(self.knowledge_choices(), multiselect=True, label="依頼文に入れる知見（任意・⑥ 知見 タブの内容）")
                intent = gr.Textbox(lines=3, label="どんな動画にしたいか", placeholder="例: 30 秒で、20 代向けに、平日ランチのお得さを伝えたい")
                with gr.Row():
                    duration = gr.Number(value=30, label="動画の長さ（秒）", minimum=5, maximum=600)
                    kind4 = gr.Radio(KIND_CHOICES, value="general", label="動画の種類")
                    mood = gr.Textbox(label="雰囲気（任意）", placeholder="例: テンポよく明るく")
                with gr.Group(visible=False) as shop_box:
                    gr.Markdown("**お店の情報**（店舗SNS のとき）")
                    shop_inputs = [gr.Textbox(label=lbl, lines=2 if k in ("menu", "other") else 1) for k, lbl in structure.SHOP_FIELDS]
                build_btn = gr.Button("骨組みを作る", variant="primary")
                sk_table = gr.Dataframe(headers=structure.SKELETON_HEADERS, interactive=True, wrap=True, label="構成の骨組み（直接書き換えOK）")
                prompt = gr.Textbox(lines=14, label="Claude 用の依頼文（コピーして claude.ai に貼る）", buttons=["copy"])
                title = gr.Textbox(label="構成案の名前")
                script = gr.Textbox(lines=10, label="完成した台本（Claude の回答を貼って保存できます）")
                with gr.Row():
                    save4 = gr.Button("構成案を保存", variant="primary")
                    dl4 = gr.Button("txt で書き出す")
                msg4 = gr.Textbox(label="メッセージ", interactive=False)
                file4 = gr.File(label="ダウンロード")
                kind4.change(lambda k: gr.update(visible=(k == "shop")), kind4, shop_box)
                refresh4.click(lambda: gr.update(choices=self.video_choices()), None, ids4)
                demo.load(lambda: gr.update(choices=self.video_choices()), None, ids4)
                demo.load(lambda: gr.update(choices=self.knowledge_choices()), None, kn4)
                build_btn.click(self.build_structure, [ids4, intent, duration, kind4, mood, kn4, *shop_inputs], [sk_table, prompt, sk_state]).then(lambda: None, None, sid_state)
                save4.click(self.save_structure, [sk_state, sk_table, prompt, title, script, sid_state], [msg4, saved, sid_state])
                saved.change(self.load_structure, saved, [sk_table, prompt, title, script, sk_state, sid_state])
                dl4.click(self.export_structure, [sk_table, prompt, title, script], file4)

            with gr.Tab("⑤ 辞書設定"):
                gr.Markdown(
                    "分析で「何回・何秒目に出たか」を数える言葉の一覧です。1 行に 1 分類、`[共通] 分類名: 言葉1、言葉2` の形で書きます。"
                    "`[店舗]` の分類は、種類が「店舗SNS」の動画だけで数えます。"
                )
                dict_text = gr.Textbox(lines=18, label="辞書")
                with gr.Row():
                    dsave = gr.Button("保存", variant="primary")
                    dreset = gr.Button("初期値に戻す")
                dmsg = gr.Textbox(label="メッセージ", interactive=False)
                demo.load(lambda: dictionary_to_text(self.dictionary), None, dict_text)
                dsave.click(self.save_dictionary, dict_text, dmsg)
                dreset.click(self.reset_dictionary, None, [dict_text, dmsg])

            with gr.Tab("⑥ 知見"):
                gr.Markdown("動画づくりに使うマーケティングの知見をまとめておく場所です。④ 構成作成で選ぶと、Claude 用の依頼文に要点が入ります。")
                kid_state = gr.State(None)
                with gr.Row():
                    ktag = gr.Dropdown(self.knowledge_tags(), value="", label="タグで絞り込む", allow_custom_value=True)
                    kpick = gr.Dropdown(self.knowledge_choices(), label="知見を選ぶ")
                    knew = gr.Button("新しく追加する")
                kview = gr.Markdown()
                with gr.Accordion("編集・追加", open=False):
                    ktitle = gr.Textbox(label="タイトル")
                    with gr.Row():
                        ksource = gr.Textbox(label="出典（動画名・記事名など）")
                        kurl = gr.Textbox(label="URL（任意）")
                        ktags = gr.Textbox(label="タグ（読点区切り）")
                    kbody = gr.Textbox(
                        lines=14, label="内容（Markdown。「## ひと言で」「## 動画づくりに使うなら」の見出しがあると、依頼文に要点だけ入ります）",
                    )
                    with gr.Row():
                        ksave = gr.Button("保存", variant="primary")
                        kconfirm = gr.Checkbox(label="本当に削除する")
                        kdel = gr.Button("この知見を削除", variant="stop")
                    kmsg = gr.Textbox(label="メッセージ", interactive=False)
                demo.load(lambda: (gr.update(choices=self.knowledge_tags()), gr.update(choices=self.knowledge_choices())), None, [ktag, kpick])
                ktag.change(lambda t: gr.update(choices=self.knowledge_choices(t), value=None), ktag, kpick)
                kpick.change(self.show_knowledge, kpick, [kview, ktitle, ksource, kurl, ktags, kbody, kid_state])
                knew.click(lambda: ("新しい知見を「編集・追加」に書いて保存してください", "", "", "", "", "## ひと言で\n\n## ポイント\n- \n\n## 動画づくりに使うなら\n- ", None), None, [kview, ktitle, ksource, kurl, ktags, kbody, kid_state])
                ksave.click(self.save_knowledge, [ktitle, ksource, kurl, ktags, kbody, kid_state], [kmsg, kpick, kid_state])
                kdel.click(self.delete_knowledge, [kid_state, kconfirm], [kmsg, kpick, kid_state])
        return demo


def launch(store: DataStore, fetcher=None, transcriber=None, sheets=None, password: str | None = None, share: bool = True, **kw):
    demo = App(store, fetcher, transcriber, sheets).build()
    auth = ("user", password) if password else None
    return demo.launch(share=share, auth=auth, auth_message="ユーザー名は user、パスワードは Colab のノートに表示されたものです", **kw)
