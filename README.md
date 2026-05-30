# Minecraft Plugin Auto Update Checker

ローカルの Minecraft サーバーで使っているプラグイン（.jar）の管理と更新確認を行うデスクトップアプリです。
GUIは Tkinter、データは SQLite に保存され、単一ファイル実装として `app.py` に主要な機能がまとまっています。

**主な機能**
- ローカルのプラグインフォルダをスキャンして `.jar` 名を登録
- Modrinth / Hangar / GitHub Releases / SpigotMC からの更新確認
- 自動マッチと、手動による取得元 URL の登録・修正
- プラグイン一覧のエクスポート（TSV, UTF-16、Windows Excel 互換）
- TSV（UTF-16 / UTF-8）からの取り込み
- サーバー単位での設定管理（プラグインフォルダ、サーバーソフト、Modrinth チャンネルなど）
- 一括更新チェック・一括ダウンロード支援
- 各 UI 要素にツールチップを表示（操作の補助）

**設計上のポイント**
- チャンネル設定（Modrinth のリリース/ベータ/アルファ等）は「サーバー管理」ダイアログ内でのみ保持されます。トップ画面のチャンネル選択は廃止されています。
- エクスポートは TSV（tab 区切り、UTF-16）を既定とし、日本語 Windows の Excel で正しく開けることを意図しています。
- サーバーごとに個別のサーバーDB（必要に応じて）を持ちます。マスターDB はユーザープロファイル下に保存されます。

**データベースの場所**
- マスター DB: `%USERPROFILE%/.minecraft_plugin_autoupdate_checker/plugin-manager.sqlite`（Windows）

**実行環境（開発向け）**
1. Python 3.10 以上を推奨
2. 仮想環境を作る場合:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. 任意で Pillow を入れるとアイコン表示が改善されます:

```powershell
pip install Pillow
```

4. アプリ起動:

```powershell
.\.venv\Scripts\python.exe app.py
# もしくは
python app.py
```

**運用上の注意**
- 更新の一括チェックは外部 API を利用します。`concurrency`（並列ワーカー数）を高く設定すると API へ負荷がかかり、アクセス制限の対象になる可能性があります。
- DB スキーマの変更はアプリ内で自動マイグレーションされますが、重要データは事前にバックアップしてください。

**開発 / 変更履歴**
- 主要な実装は `app.py` 内にあります。UI や動作を変更する場合はまず `app.py` を参照してください。

---
最新の変更やプルリクエストは GitHub のリポジトリで確認してください。