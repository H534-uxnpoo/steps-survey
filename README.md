# STEPS Survey Scanner

Phase 1〜3の縦スライスです。ブラウザからJPEG/PNGのアンケート画像を1枚アップロードし、FastAPI/OpenCVで用紙を補正して、公演回と年齢のチェックボックスを表示します。

この段階ではOCR、Google Sheets、裏面、他の設問、登録・編集画面は実装しません。アップロード画像は永続保存しません。

## 起動

Python 3.11以降とNode.js 20以降を用意します。

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

別の端末で、フロントエンドを起動します。

```powershell
cd frontend
npm install
npm run dev
```

`http://localhost:3000` を開きます。バックエンドURLを変更する場合は、`frontend/.env.local` に `NEXT_PUBLIC_API_BASE_URL` を設定します（秘密情報は置かないでください）。

## テスト

```powershell
.venv\Scripts\python.exe -m pytest backend\tests -q
```

`test-data/private/` にJPEG/PNGがある場合、テストはその画像をメモリ内で読み取り、個人情報を出力せずにPhase 3の処理が完了することだけを確認します。画像やその内容は保存・表示しません。

## Phase 3の一括精度検証

非公開画像をまとめて検証するには、`test-data/private/phase3_labels.json` に画像ファイル名をキーとした正解ラベルを置きます。このファイルは `.gitignore` の対象です。形式は [ラベル例](test-data/phase3_labels.example.json) を参照してください。補正不能などで正解を確認できない項目は `null` にできます。ラベルがない画像は評価対象外として `missingLabels` に集計されるため、画像の追加や並べ替えで既存ラベルはずれません。

```powershell
.venv\Scripts\python.exe backend\scripts\validate_phase3.py
```

出力にはファイル名・画像・回答値を含めず、`sample-001` のような連番、補正成否、正否、要確認だけを含めます。

## Phase 4: メッセージOCR

補正済みアンケートのメッセージ欄だけを、`survey_template.json` の `message.roi` に従ってメモリ上で切り出し、Google Cloud Vision APIへ送ります。元画像・crop画像・OCR本文は保存またはログ出力しません。OCRはデフォルトで無効です。

ローカルで有効化する場合は、Google Cloud Vision APIを有効化したプロジェクトの認証情報をリポジトリ外に置き、バックエンドの環境変数に設定します。

```powershell
$env:VISION_OCR_ENABLED = "true"
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\secure\vision-service-account.json"
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

Cloud Runでは鍵ファイルを置かず、Cloud Vision API User 権限を持つサービスアカウントを実行サービスに割り当てます。認証情報や `VISION_OCR_ENABLED` はFrontendに設定しません。

通常の自動テストはVisionを呼びません。実APIテストは課金と非公開メッセージ欄の送信を明示的に許可したときだけ実行してください。

```powershell
$env:VISION_OCR_ENABLED = "true"
$env:RUN_VISION_INTEGRATION = "1"
.venv\Scripts\python.exe -m pytest -m integration backend\tests\integration -q
```
