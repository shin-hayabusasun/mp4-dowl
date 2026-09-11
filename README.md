# YouTube Downloader

ローカルで動く YouTube ダウンロード用Webアプリです。自分が権利を持つ動画、または権利者から保存を許可された動画だけに使用してください。

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

ブラウザで `http://127.0.0.1:5000` を開きます。

保存先は `downloads/` です。
