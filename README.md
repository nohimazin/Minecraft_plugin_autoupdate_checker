# Minecraft Plugin Auto Update Checker

Minecraft サーバーで使っているプラグインのファイル名からバージョンを読み取り、SQLite データベースに登録して更新確認と一括ダウンロードを行う軽量デスクトップアプリです。

Modrinth、Hangar、GitHub Releases、SpigotMC の更新情報を参照できます。

## できること

- プラグインフォルダ内の `.jar` からファイル名ベースでバージョンを抽出して登録
- SQLite にローカルプラグイン情報を保存
- 「更新を確認」で Modrinth / Hangar / GitHub Releases / SpigotMC から更新候補を検索
- 更新があれば画面に反映し、一括ダウンロードを確認
- 配布元のアイコンを表示し、取得元ページを開ける
- ダウンロード先フォルダを選んで更新版をまとめて保存
- 手動で配布元 URL を指定して登録先を修正できる

## 起動方法

1. Python 3.10 以上を用意します。
2. Windows ではそのまま `python app.py` で起動します。
3. Ubuntu 系では Tkinter が必要です。入っていない場合は `python3-tk` を追加してください。
4. `app.py` を起動し、プラグインフォルダを選択してからスキャンします。

## 補足

- データベースはユーザーフォルダ配下の `.minecraft_plugin_autoupdate_checker/plugin-manager.sqlite` に保存されます。
- 更新確認は登録済みの配布元を優先し、未登録のものは Modrinth / Hangar を順に探します。
- SpigotMC は resource ID を使って追跡します。配布元ページは SpigotMC 側を開きます。
- どの配布元も見つからない場合でも、ローカル版の登録と一覧管理は継続して使えます。