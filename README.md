# Minecraft Plugin Auto Update Checker

Paper サーバーで使っているプラグインのファイル名からバージョンを読み取り、SQLite データベースに登録して更新確認と一括ダウンロードを行う軽量デスクトップアプリです。

Electron は使わず、Python 標準ライブラリの Tkinter で動くため、Windows と Ubuntu 系で使いやすい構成にしています。

## できること

- プラグインフォルダ内の `.jar` からファイル名ベースでバージョンを抽出して登録
- SQLite にローカルプラグイン情報を保存
- 「更新を確認」で Modrinth から更新候補を検索
- 更新があれば画面に反映し、一括ダウンロードを確認
- ダウンロード先フォルダを選んで更新版をまとめて保存

## 起動方法

1. Python 3.10 以上を用意します。
2. Windows ではそのまま `python app.py` で起動します。
3. Ubuntu 系では Tkinter が必要です。入っていない場合は `python3-tk` を追加してください。
4. `app.py` を起動し、プラグインフォルダを選択してからスキャンします。

## 補足

- データベースはユーザーフォルダ配下の `.minecraft_plugin_autoupdate_checker/plugin-manager.sqlite` に保存されます。
- 更新確認はまず Modrinth を探します。Modrinth にないプラグインは更新元を特定できない場合があります。
- その場合でもローカル版の登録と一覧管理は継続して使えます。