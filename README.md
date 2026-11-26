# TikTok 文字起こし・分析ツール

TikTok 動画の URL を貼ると、全編を文字起こしして Google ドライブに保存し、話し方・構成の傾向を分析、自分の動画の構成案（＋ Claude 用の依頼文）を作るツールです。Google Colab で動くので、Mac には何も入れません。

## 使い方

1. 下のリンクから Colab でノートを開く（Google アカウントでログイン）
   - https://colab.research.google.com/github/Daiki9615/TiTok-/blob/claude/beautiful-cori-0ern9t/notebooks/TikTok_Transcriber.ipynb
2. ▶ を 1 回押す
3. Google の画面が出たら自分のアカウントを選んで「許可」
4. 下に出るリンクを開き、表示されたパスワードでログイン


## 画面

| タブ | できること |
|---|---|
| ① 取り込み | URL をまとめて貼る → 全編文字起こし → 保存（失敗した動画は理由を表示して続行） |
| ② 一覧・閲覧 | 絞り込み・検索、全文（時刻つき）の表示と手修正、txt / srt / csv 書き出し |
| ③ 分析 | 1 本から分析。つかみ（最初の 3・5 秒）、締め（最後の 5 秒）、頻出語、話す速さ、辞書の言葉、グループ比較、言葉と再生数 |
| ④ 構成作成 | 参考動画と「どんな動画にしたいか」から骨組みを作り、claude.ai に貼る依頼文を作成。店舗 SNS 用は店舗情報も反映 |
| ⑤ 辞書設定 | 分析で数える言葉の一覧を編集 |

## 保存場所

- `マイドライブ/TikTok文字起こし/videos/` … 1 動画 1 ファイル（JSON）
- `マイドライブ/TikTok文字起こし/structures/` … 構成案
- スプレッドシート「TikTok文字起こしデータ」… 一覧（ノートの 3 番で連携オンのとき）

## 開発

```bash
pip install -r requirements-dev.txt
pytest -q
```

要件定義: [docs/requirements.md](docs/requirements.md)
