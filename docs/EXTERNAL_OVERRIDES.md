# External overrides repository — 移行と検証手順

目的: `overrides.json` をアプリ本体から分離し、別リポジトリで配布・管理するための最小手順。

1. リポジトリ作成
  - 新しいリポジトリ（例: `minecraft-plugin-overrides`）を作成し、`overrides.json` を置く。

2. リリース/公開
  - GitHub のリリースに `overrides.json` を含めるか、`raw` URL で直接参照可能にする。
  - 望ましくはリリースごとにタグを付け、固定 URL を使う。

3. セキュリティ
  - アプリは環境変数 `OVERRIDES_URL` にその raw URL を入れて取得する。
  - オプションで `OVERRIDES_SHA256` に期待ハッシュを設定して整合性を検証することを強く推奨します。

4. CI / 検証
  - 別リポジトリの PR で JSON スキーマ検証を通過させる（キーは文字列、値はオブジェクト）。
  - 可能なら署名（GPG/PEM）を併用し、配布物の信頼性を高める。

5. テスト（ローカル）
  - リポジトリのルートにある `overrides.json` を HTTP サーバで配信して、アプリ側で環境変数を使って取得を確認できます。
  - 本リポジトリにテストスクリプトがあり、次のコマンドで実行します:

```bash
python -3 tests/fetch_overrides_test.py
```

6. フォールバック
  - アプリはまず `OVERRIDES_URL` を試し、失敗時はスクリプト同梱の `overrides.json`、さらにキャッシュ（`~/.minecraft_plugin_autoupdate_checker/overrides.json`）へフォールバックします。

運用例: CI が `overrides.json` を更新しタグ付きリリースを作成→アプリは `OVERRIDES_URL` をそのリリースの raw URL に向ける。ハッシュを環境に設定している場合は CI がハッシュをトリガでアプリ側設定に反映する必要があります（あるいはアプリ側で定期的に署名鍵で検証する）。
