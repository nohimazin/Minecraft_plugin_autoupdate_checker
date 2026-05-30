# Patch Summary

このパッチセットは主に `app.py` の DB とサーバー管理周りの安定化・整理を目的としています。

## 変更点（主なもの）
- DB 初期化とマイグレーション
  - `PluginDatabase` に `_init_plugins_schema(conn)` を追加し、サーバーごとの DB を開く際に正しく `plugins` テーブルを作成するようにした。
  - マスター側スキーマの互換カラム処理を整理（`latest_version_id`, `server_id` の追加処理を統合）。

- サーバー管理 UI 挙動の修正
  - サーバー管理ダイアログで新規作成が既存サーバーを上書きする不具合を修正（`new_server()` が `selected_index=None` を設定するように）。
  - ダイアログを閉じた際にメイン UI を再読み込みするように (`dialog.wait_window()` + `_load_servers_to_ui()`)。
  - ダイアログを開いたときに最初のサーバーを自動選択するようにした。
  - `save_server()` にて保存後に `selected_server_id` を設定、`open_server_db()` を呼ぶ、メイン画面の `StringVar` を即時更新するように変更。

- UI と選択反映の整理
  - `_load_servers_to_ui()` 内の選択処理を中央化し、選択時にメイン UI へ反映するロジックを `_apply_server_row_to_ui()` に集約。
  - `_on_server_combo_changed()` でも同 helper を利用するように重複を削除。

- ロギング・ドキュメント
  - DB 操作（create/update/delete/open）に debug ログを追加（`logging` を利用）。
  - `docs/DESIGN.md` と `docs/TESTING.md` を追加。
  - `scripts/check_db.py` を追加し、DB の簡易整合性チェックが実行可能に。

## 影響範囲
- 主要変更は `app.py` 内。ファイル分割は行っていないため外部参照は不要。
- 挙動の変更点は主にサーバー作成/保存・起動時のサーバー選択周り。

## テスト手順（短縮）
1. アプリを終了して再起動。既存サーバーが main のコンボボックスに表示されること。
2. サーバー管理を開き、先頭サーバーが選択されていること。
3. 既存のサーバーを選択して編集→保存。メイン UI に即時反映されること。
4. 新規作成を押してフォームを埋めて保存。既存が上書きされず新しい行が追加されること。
5. `py -3 scripts\check_db.py` を実行し、マスター DB と各サーバー DB に `plugins` テーブルが存在することを確認する。

## 推奨コミットメッセージ
```
Fix: stabilize server manager and per-server DB initialization

- Initialize per-server plugins schema when opening server DB
- Fix new-server overwrite bug and ensure UI reflects saves immediately
- Centralize server->UI apply logic
- Add debug logging, design/testing docs and DB check script
```

---

必要ならこの差分をまとめて Git のブランチにコミットし、PR 用の説明を作成します。希望があればお知らせください。