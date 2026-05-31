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

## overrides.json (誤判定防止とヒント用辞書)

このリポジトリには `overrides.json` を置くことで、自動マッチの誤判定を抑制したり、特定プラグインの取得元を明示することができます。ファイルは `app.py` と同じディレクトリに配置すると自動的に読み込まれます。

基本構造（キーは正規化されたプラグイン名: normalize_modrinth_lookup の結果を使用）:

```json
{
	"normalizedpluginname": {
		"preferred_source": { "type": "modrinth", "id": "nbtapi", "url": "https://modrinth.com/plugin/nbtapi" },
		"spiget_ignore": ["222", "37"],
		"file_paths": ["listing://item-nbt-api-plugin-2.15.5.jar"],
		"file_name_prefixes": ["item-nbt-api-plugin"]
	}
}
```

フィールドの意味:
- `preferred_source` (オプション)
	- `type`: `modrinth`, `hangar`, `github`, `spiget`, `manual` など。アプリ内での優先取得元を明示します。
	- `id`: 取得先を一意に示す識別子（Modrinth の project id、Hangar の ref、GitHub の owner/repo など）。
	- `url`: その取得元のホームページやプロジェクトページ（オプション）。UI の表示や手動修正時の候補として利用できます。

- `spiget_ignore` (オプション)
	- Spiget / SpigotMC の resource id のリスト。自動マッチ時にこれらの id を候補から除外します。

- `file_paths` (オプション)
	- 具体的な `file_path`（例: `listing://...`）の一覧。将来的にファイルパスから直接優先取得元を割り当てる用途を想定しています（現時点では参考情報として扱われます）。

- `file_name_prefixes` (オプション)
	- jar 名のプレフィックス一覧。バージョン違いの複数ファイルをまとめて扱うためのヒントとして使えます（現時点では参考情報）。

現在の実装上の挙動:
- `preferred_source` と `spiget_ignore` は `search_spiget_project` 側で参照され、該当する場合は Spiget の自動マッチを回避します（`preferred_source` がある場合は Spiget マッチを行わず、その代わり他の提供元を利用する運用を想定しています）。
- `file_paths` / `file_name_prefixes` は辞書内に保存され、今後の自動割当やインポート時のヒントとして利用される予定です。

運用例:
- item-nbt-api-plugin のように短いトークンで誤判定を受けやすいプラグインは、`normalized` キー（例: `itemnbtapi` や `nbtapi`）を作り、`preferred_source` に Modrinth の project id と URL を設定しておくと安心です。

セキュリティ/運用上の注意:
- このファイルはローカルで編集してカスタム運用することを想定しています。配布用にコミットする場合は、公開して問題ない設定のみを含めてください（プライベート情報は含めないでください）。

必要なら、README に `overrides.json` の編集例や自動生成スクリプトのテンプレートを追加します。希望があれば教えてください。