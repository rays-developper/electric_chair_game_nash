# electric_chair_game_nash
電気椅子ゲームのナッシュ均衡値を求める

## 事前計算テーブル + ブラウザUI

### 1) 生成ファイルの保存先

- 本番DB: `data/equilibrium_lookup.sqlite3`
- 進捗ログ: `data/build_progress.log`

### 2) 事前計算データを新規生成

```bash
python -m electric_chair_game.build_lookup_table \
	--db data/equilibrium_lookup.sqlite3 \
	--progress-interval 5000 \
	--save-interval 5000 \
	--log-file data/build_progress.log
```

CPU並列で高速化する場合（新規生成時）:

```bash
python -m electric_chair_game.build_lookup_table \
	--db data/equilibrium_lookup.sqlite3 \
	--workers 8 \
	--progress-interval 5000 \
	--save-interval 5000 \
	--log-file data/build_progress.log
```

- `--workers` はCPUコア数に合わせて調整してください。
- 並列モードは初期局面の直後分岐をプロセス分散して計算し、最後に統合します。

- 初期状態（0点 / 0被弾 / 椅子1-12）から、到達可能な状態だけをメモ化再帰で探索します。
- 検索済み状態はチェックポイント間隔ごとにDBへ書き込みます。

### 3) 中断後に途中から再開

```bash
python -m electric_chair_game.build_lookup_table \
	--db data/equilibrium_lookup.sqlite3 \
	--resume \
	--progress-interval 5000 \
	--save-interval 5000 \
	--log-file data/build_progress.log
```

- `--resume` で既存DBを読み込み、未計算分だけ続きから埋めます。
- 停止しても、次回同じ `--db` + `--resume` で再開できます。

### 4) 進捗ログを確認

```bash
tail -f data/build_progress.log
```

```bash
tail -n 50 data/build_progress.log
```

必要ならDB側の進捗も確認できます。

```bash
python - <<'PY'
import sqlite3
con = sqlite3.connect('data/equilibrium_lookup.sqlite3')
print(con.execute('select count(*) from equilibrium_lookup').fetchone()[0])
con.close()
PY
```

### 5) 状態定義（roundを持たない）

- 状態キーは圧縮キー（点数・被弾数・椅子集合マスク）です。ラウンドは
	`被弾数合計 + 撤去椅子数 + 1` で導出します。
- 理論状態空間は `40*40*3*3*2^12 = 58,982,400` です。

### 6) UIサーバを起動

```bash
python -m electric_chair_game.lookup_server --db data/equilibrium_lookup.sqlite3 --memory-cache
```

- `--memory-cache` を指定すると、起動時に全行をメモリ上の `dict` にロードします。
- 以後の検索はハッシュキー検索（平均 O(1)）です。
- ブラウザで `http://127.0.0.1:8000` を開いて検索できます。

### 7) API

- `GET /api/stats`
- `GET /api/lookup?attacker_points=0&defender_points=0&attacker_shocks=0&defender_shocks=0&chairs=1,2,3,...,12`

---

## GitHub Pages で公開

バックエンド不要の静的サイトとして `docs/` フォルダが用意されています。

### セットアップ

1. **リポジトリをGitHubにプッシュ**
2. **Settings → Pages → Source** を `main` ブランチの `/docs` フォルダに設定
3. 数分後に `https://<username>.github.io/<repo>/` でアクセス可能

### データ範囲

- `docs/data/equilibrium.json` には **ゲーム序盤（ポイント合計10以下）** の約52,000件が含まれています。
- 全状態が必要な場合は、以下でJSONを再生成できます:

```bash
python scripts/export_json.py --output docs/data/equilibrium.json
```

- `--limit N` で件数を制限し、ファイルサイズを調整できます。

### ローカルテスト

```bash
cd docs && python3 -m http.server 8000
# ブラウザで http://localhost:8000 を開く
```

