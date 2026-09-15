# STEPS Survey Scanner

Phase 1〜6、8を含むアンケート読取・確認画面と、確認済みデータのコピー支援を実装しています。ブラウザからJPEG/PNGを1枚処理し、確認・修正した11項目を個別にコピーして既存Googleフォームへ手動転記できます。

Googleフォームへの自動入力・自動送信は行いません。最終送信は人間がGoogleフォーム上で行います。アップロード画像、crop画像、OCR本文、コピー内容は永続保存しません。

## 通常の利用フロー

1. アプリでアンケート画像を読み込む
2. 認識結果を確認・修正する
3. 必要な項目の「コピー」を押す
4. 「Googleフォームを開く」で既存フォームを別タブに開く
5. Googleフォームへ貼り付け・選択する
6. Googleフォームで人間が送信する
7. アプリへ戻り「次のアンケートを読み取る」を押す

表面解析後は「裏面も読み取る」または「裏面なし」を選択できます。裏面を読み取る場合は、撮影・写真選択・プレビュー確認後に自由記述OCRを行い、結果をメッセージ欄へ「【裏面】」付きで追加します。OCR未設定時は要確認として手入力できます。

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

## Google Sheets（現在の通常運用では使用しない）

既存のGoogle Sheets provider・API・テストは将来の開発用として残っていますが、通常のユーザー操作フローからは呼び出しません。Google Sheets認証は現在の正式運用には不要です。

認証未設定時の既定値は `SHEETS_ENABLED=false` で、登録APIは `sheets_unavailable` を返し、成功表示や代替ファイル保存は行いません。

（参考）将来Sheets運用へ戻す場合の設定例（通常運用では不要）:

```powershell
$env:SHEETS_ENABLED = "true"
$env:SHEETS_SPREADSHEET_ID = "your-spreadsheet-id"
$env:SHEETS_RANGE = "アンケート!A:K"
gcloud auth application-default login
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

Cloud Runでは、Sheets API権限を持つ実行サービスアカウントを割り当てます。`GOOGLE_APPLICATION_CREDENTIALS` を使う場合も、JSON鍵はリポジトリ外に置きます。

対象シートの `A1:K1` が固定ヘッダーと一致しない場合は登録を中止します。APIは `values.append`、`valueInputOption=RAW`、`insertDataOption=INSERT_ROWS` を使用します。
