**Overrides 書式 (overrides.json)**

- **目的**: 自動マッチの誤判定を運用レベルで回避するための外部辞書フォーマット。アプリは起動時に `overrides.json` を読み込み、キーにマッチする行を優先して扱います。

**基本構造**

- ファイルは JSON オブジェクトで、キーは正規化済みプラグイン名（`normalize_modrinth_lookup()` の出力に相当）を使用します。
- 値はオブジェクトで、以下のフィールドを持ちます。

例:

```json
{
  "itemnbtapi": {
    "preferred_source": "modrinth",
    "spiget_ignore": ["222", "37"],
    "file_paths": ["listing://nbtapi.jar"],
    "file_name_prefixes": ["nbtapi", "item-nbt-api"]
  }
}
```

**フィールド説明**

- `preferred_source` (任意): `modrinth` / `hangar` / `spiget` / `github` / `manual` / `listing` のいずれか。指定された場合、アプリはその提供元を優先して解決を試みます。指定元に互換リリースが存在しない場合、意図しないフォールバックを防ぐために他ソースへ自動でフォールバックしません（結果は「更新なし」として扱われます）。

- `spiget_ignore` (任意): Spigot 側検索結果のうち無視する `id` の配列。文字列または数値で指定可能。Spiget の誤検出を除外するのに有効です。

- `file_paths` (任意): ファイル由来で明示的に紐づけたい場合に使う配列。`listing://` で始まるローカルリスト参照を含められます。例: `"listing://floodgate-spigot.jar"`。

- `file_name_prefixes` (任意): ファイル名や JAR 名の接頭辞リスト。アプリは `file_name_prefixes` のいずれかが一致するかを見て辞書にマッチとみなします。接頭辞マッチは厳密（トークン境界やハイフン区切り等により誤一致を防止）です。

**キーの作り方**

- キーは `normalize_modrinth_lookup(value)` を想定した正規化済み（小文字化＋英数字のみ）文字列にしてください。例えば `item-nbt-api-plugin` → `itemnbtapiplugin`、`Geyser-Floodgate` → `geyserfloodgate`。

**運用ルールと注意点**

- `preferred_source` を指定した場合、その提供元での明示的な確認が優先され、見つからなければ自動フォールバックしないため、誤ったフォールバックによる DB 上書きを防げます。
- 安全のため、`spiget_ignore` で誤判定となった Spiget の `id` を列挙することを推奨します。
- `file_name_prefixes` は短すぎるトークン（例: `server`, `paper`）を避け、十分に識別性のある接頭辞を使ってください。
- このファイルは配布可能ですが、外部から取り込む場合は内容の検証（署名や信頼できるホスト経由）を行ってください。任意の `preferred_source` による挙動変更は運用上の意図がある場合のみ使ってください。

**実例 (floodgate-spigot の例)**

```json
"floodgatespigot": {
  "preferred_source": "hangar",
  "file_name_prefixes": ["floodgate-spigot"],
  "file_paths": ["listing://floodgate-spigot.jar"],
  "spiget_ignore": ["82278"]
}
```

**フォーマット上の制約**

- JSON であること。
- 既存のキーと重複する場合、最後に読み込まれたファイルが適用されます（通常はリポジトリ内の `overrides.json` が優先されます）。

---

質問があれば、この文書に例を追加したり、アプリ内で編集できる UI 向けの仕様を書き起こします。
