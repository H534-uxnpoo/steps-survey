# STEPS Survey Scanner — MVP仕様書

## 1. プロジェクト概要

STEPS Musical Company 第69回本公演『Cliché』の紙アンケートを、
スマートフォンで書類のようにスキャンし、回答内容を読み取って
Googleスプレッドシートへ登録するWebアプリを開発する。

対象アンケートは今回の公演中、すべて同一レイアウトとする。

想定処理枚数は約200枚。

複数人がそれぞれのスマートフォンから利用し、
全員の読み取り結果を1つのGoogleスプレッドシートへ登録する。


---

# 2. 基準ファイル

未記入の基準アンケート:

`reference/questionnaire_blank.pdf`

記入済みテスト画像:

`test-data/private/`

基準アンケートは固定レイアウトとして扱う。

撮影されたアンケートを基準アンケートと同じ座標系へ補正したうえで、
チェックボックスや各記入領域を解析する。

`test-data/private/` には個人情報が含まれる可能性があるため、
Git管理対象にしてはいけない。


---

# 3. 技術構成

## Frontend

- Next.js
- TypeScript
- スマートフォン優先UI
- 将来的にPWA化可能な構成

## Backend

- Python
- FastAPI

## 画像処理

- OpenCV

## OCR

MVP後半で以下を使用する。

- Google Cloud Vision API

主に手書き文字の読み取りに使用する。

## データ保存

- Google Sheets API

## デプロイ候補

Frontend:

- Vercel

Backend:

- Google Cloud Run

本番環境の通信はすべてHTTPS/TLSとする。


---

# 4. 基本処理フロー

```text
スマートフォン
    ↓
アンケートをスキャン
    ↓
画像をBackendへ送信
    ↓
OpenCV
    ├─ 用紙検出
    ├─ 四隅検出
    ├─ 台形補正
    ├─ 回転補正
    ├─ サイズ正規化
    └─ テンプレート位置合わせ
    ↓
チェックボックス判定
    ↓
手書き領域をcrop
    ↓
Google Cloud Vision API
    ↓
OCR結果を構造化
    ↓
確認画面
    ↓
必要箇所を人間が修正
    ↓
Google Sheets API
    ↓
1回答 = 1行として登録
```


---

# 5. スキャン機能

メインの入力方法はスマートフォンのカメラとする。

通常の写真撮影ではなく、
書類スキャンアプリに近いUXを目標とする。

## カメラ画面

可能な範囲で以下を実装する。

- 用紙の輪郭検出
- 四隅検出
- 用紙枠の画面表示
- 撮影
- 台形補正
- 回転補正
- コントラスト等の補正
- 撮影結果プレビュー
- 撮り直し

撮影後、

- この画像を使用
- 撮り直す

を選択できるようにする。

## 画像アップロード

カメラとは別に、

「写真から選択」

を用意する。

最低限、

- JPEG
- PNG

に対応する。

HEICについては、MVP後半または必要になった段階で対応する。


---

# 6. 将来の一括アップロード

MVPでは1枚ずつの処理を基本とする。

ただし将来的に、

- 複数JPEG/PNG
- スキャン済み画像
- PCからのドラッグ&ドロップ

などを一括処理できる構造にする。

MVPでは一括処理UIを実装する必要はない。


---

# 7. Googleスプレッドシート

1アンケート = 1行とする。

列は以下の順番とする。

1. 公演回
2. 年齢
3. きっかけ
4. 宣伝媒体
5. 予約のスムーズさ
6. メッセージ
7. 名前
8. 案内希望者名
9. 郵便番号
10. 住所
11. メアド

登録日時、画像ID、confidence等の管理列は
MVPではGoogleスプレッドシートに追加しない。


---

# 8. 公演回

チェックボックスをOpenCVで判定する。

選択肢:

- 12日(土)12:30-
- 12日(土)17:30-
- 13日(日)12:30-

基本的に1つだけ選択される想定。

複数のチェックが検出された場合、
自動的に1つへ決めず `needsReview = true` とする。


---

# 9. 年齢

チェックボックスをOpenCVで判定する。

選択肢:

- 10代以下
- 20代
- 30代
- 40代
- 50代
- 60代以上

複数検出された場合は要確認とする。


---

# 10. きっかけ

複数選択可能。

選択肢:

- 関係者親族
- STEPSのOB・OG
- 関係者の誘い
- 慶應生
- 劇協
- SNSをみて
- 置きチラシをみて
- その他

複数選択されている場合でも、
Google Sheetsでは1セルへ格納する。

例:

`関係者親族, SNSをみて`

## 関係者の誘い

関係者名の記入がある場合、

`関係者の誘い（山田）`

の形式にする。

## その他

自由記述がある場合、

`その他（友人から聞いた）`

の形式にする。

例:

`関係者の誘い（山田）, SNSをみて, その他（友人から聞いた）`

関係者名とその他の自由記述部分のみOCR対象とする。


---

# 11. 宣伝媒体

複数選択可能。

選択肢:

- X
- Instagram
- Facebook
- ホームページ
- PV
- DM
- 公演チラシ
- ブログ
- その他

複数選択の場合も1セルへ格納する。

例:

`Instagram, 公演チラシ, その他（LINE）`

「その他」の自由記述部分のみOCR対象とする。


---

# 12. 予約のスムーズさ

選択肢:

- できた
- わかりにくかった
- その他

その他に記述がある場合、

`その他（記述内容）`

とする。


---

# 13. メッセージ

自由記述欄をOCRする。

この領域はOpenCVでcropした後、
Google Cloud Vision APIへ送る。

## OCR方針

可能な限り原文をそのまま文字起こしする。

以下を行わない。

- 要約
- 言い換え
- 文法修正
- 内容の推測
- 読めない文字の勝手な補完

部分的に読み取れる場合は、
読み取れた範囲を提示して `needsReview = true` とする。


---

# 14. 裏面

表面の読み取り後、

「裏面も読み取る」

を表示する。

選択肢:

- 裏面も読み取る
- 裏面なし

裏面を読み取る場合、
再度カメラを起動する。

裏面は固定フォームとして扱わず、
基本的に用紙全体を自由記述としてOCRする。

表面と裏面の文章は、
Google Sheetsの「メッセージ」セルへまとめる。

例:

```text
とても楽しかったです。

【裏面】
特に第二幕の演出が好きでした。
```


---

# 15. 名前

アンケートには氏名欄が2か所存在する。

## 上部

「お名前（任意）」

Google Sheets:

`名前`

## 下部

次回以降の公演案内希望者欄の氏名。

Google Sheets:

`案内希望者名`

2つを混同しない。

両方記入されている場合も、それぞれ別に保存する。


---

# 16. 郵便番号と住所

案内希望者欄の住所から、

- 郵便番号
- 住所

を分離する。

例:

```text
〒123-4567
東京都○○区...
```

↓

```text
郵便番号:
123-4567

住所:
東京都○○区...
```

郵便番号に `〒` は保存しない。

可能であれば、

`NNN-NNNN`

形式かvalidationする。

形式が怪しい場合は勝手に修正せず、
要確認にする。


---

# 17. メールアドレス

手書きメールアドレスをOCRする。

メール形式の簡易validationを行う。

特に以下の誤認識に注意する。

- 0 / O
- 1 / l / I
- . / ,
- - / _
- @ の欠落

OCR結果から推測して勝手に修正しない。

メールアドレスは他の項目より
厳しめに要確認判定する。


---

# 18. テンプレート位置合わせ

スマートフォン撮影では、

- 回転
- 台形歪み
- 撮影距離
- トリミング
- 光量
- 影

などが毎回異なる。

撮影画像から用紙の四隅を検出し、
perspective transformを行う。

その後、

`reference/questionnaire_blank.pdf`

と同一の座標系へ変換する。

必要であれば印刷部分の特徴点等を使用して
fine alignmentを行う。


---

# 19. 座標設定

チェックボックスや記入欄の座標を
Pythonコード内へ直接散在させない。

設定ファイルへまとめる。

例:

`backend/app/config/survey_template.json`

概念例:

```json
{
  "performance": {},
  "age": {},
  "trigger": {},
  "media": {},
  "reservation": {},
  "message": {},
  "name": {},
  "mailing_name": {},
  "postal_code": {},
  "address": {},
  "email": {}
}
```

実際の座標は原本PDFを解析して決定する。


---

# 20. チェックボックス検出

チェックボックスは原則としてAI/OCRではなく、
OpenCVで判定する。

基本処理候補:

1. grayscale
2. threshold
3. ROI抽出
4. checkbox内部のink ratio計算
5. thresholdによる判定

ただし、印刷されている四角枠そのものを
チェックとして誤認しないようにする。

可能であれば、
未記入テンプレートとの差分を利用する。

概念:

```text
記入済みROI
-
未記入テンプレートROI
=
手書き筆跡
```

threshold値は設定ファイル化し、
実アンケートを使って後から調整できるようにする。


---

# 21. OCR対象

可能な限りアンケート画像全体を
Google Cloud Vision APIへ送らない。

位置合わせ後に必要領域のみcropする。

OCR対象:

- メッセージ
- 名前
- 案内希望者名
- 郵便番号
- 住所
- メールアドレス
- 関係者名
- 各「その他」の自由記述
- 裏面

チェックボックスは原則として
Google Cloud Vision APIへ送らない。


---

# 22. 認識結果

各項目は内部的に以下の情報を持てるようにする。

```typescript
type FieldResult = {
  value: string;
  confidence: number;
  needsReview: boolean;
};
```

アンケート全体:

```typescript
type SurveyResult = {
  performance: FieldResult;
  age: FieldResult;
  trigger: FieldResult;
  media: FieldResult;
  reservation: FieldResult;
  message: FieldResult;
  name: FieldResult;
  mailingName: FieldResult;
  postalCode: FieldResult;
  address: FieldResult;
  email: FieldResult;
};
```

confidenceの数値そのものを
一般ユーザーへ表示する必要はない。


---

# 23. 要確認

認識に自信がない場合、

`needsReview = true`

とする。

AI/OCR/画像処理が推測して
確定値を作らないこと。

特に以下を慎重に扱う。

- メールアドレス
- 名前
- 住所
- 郵便番号
- 自由記述
- 複数チェックの可能性
- チェック判定の境界値


---

# 24. 確認画面

OCR・画像認識終了後、
Google Sheetsへ即時登録しない。

必ず確認画面を表示する。

表示項目:

- 公演回
- 年齢
- きっかけ
- 宣伝媒体
- 予約のスムーズさ
- メッセージ
- 名前
- 案内希望者名
- 郵便番号
- 住所
- メアド

すべてユーザーが修正可能とする。

高confidence:

通常表示。

低confidence:

「要確認」として視覚的に強調する。

最下部:

`スプレッドシートに登録`

登録成功後:

`登録しました`

さらに、

`次のアンケートをスキャン`

を表示する。

約200枚を連続処理するため、
次のアンケートまでの操作数を少なくする。


---

# 25. Google Sheets連携

複数人がアプリを使用しても、
全員が同一Google Spreadsheetへ登録する。

概念:

```text
スマホA ─┐
スマホB ─┼→ Backend → Google Sheets API → 1つのSpreadsheet
スマホC ─┘
```

クライアントから直接Google Sheets APIを呼ばない。

Google API認証情報はBackendのみが保持する。

Google Spreadsheet IDをBackendの環境設定として保持する。

1アンケートごとに1行をappendする。

複数人が同時に送信した場合にも、
行を上書きせず安全にappendできるようにする。


---

# 26. API構成案

## POST /api/scan/front

入力:

`multipart/form-data`

- image

処理:

- 用紙検出
- 補正
- checkbox解析
- OCR

出力例:

```json
{
  "scanId": "random-id",
  "fields": {},
  "needsReview": true
}
```

## POST /api/scan/back

入力:

- scanId
- image

出力:

```json
{
  "backMessage": "",
  "confidence": 0,
  "needsReview": false
}
```

## POST /api/submit

確認済みのSurveyResultを受け取る。

Google Sheetsへ1行appendする。

成功:

```json
{
  "success": true
}
```


---

# 27. 画像の保存

アップロードされたアンケート画像は
永続保存しない。

原則:

```text
upload
↓
memory
↓
image processing
↓
必要領域のみOCR
↓
結果返却
↓
画像破棄
```

データベースやGoogle Drive等へ
元画像を保存しない。


---

# 28. ログ

個人情報をログに出力しない。

ログに含めてはいけないもの:

- アンケート画像
- Base64画像
- 名前
- 住所
- 郵便番号
- メール
- メッセージ
- OCR全文
- request body

ログに含めてよいもの:

- ランダムな処理ID
- 成功/失敗
- 個人情報を含まないエラーコード
- HTTP status
- 処理時間

例:

```text
scan_id=abc123 status=success duration_ms=1820
```


---

# 29. Secrets

以下をFrontendへ含めない。

- Google API key
- Service Account credentials
- Private key
- Spreadsheetへの認証情報

環境変数またはSecret Managerを使用する。

秘密情報をGitへcommitしない。


---

# 30. エラー処理

以下を想定する。

- 用紙が検出できない
- 用紙全体が写っていない
- ピンぼけ
- 暗すぎる
- 影
- 強い反射
- テンプレート位置合わせ失敗
- OCR API timeout
- OCR API error
- Sheets API error
- network error

用紙認識失敗時は、

「アンケート全体が画面に入るように撮影してください」

など、人間が次に何をすればよいか分かるメッセージを表示する。

Sheetsへの登録失敗時、
確認済みデータを即座に消さない。

再送できるようにする。


---

# 31. Phase 1

目的:

基準アンケートを解析できる状態を作る。

実装:

- Next.js frontendの最小構成
- FastAPI backendの最小構成
- `questionnaire_blank.pdf` の読み込み
- 基準画像への変換
- 座標系の決定
- 画像アップロードUI


---

# 32. Phase 2

目的:

スマートフォン等で撮影したアンケートを
基準座標へ変換する。

実装:

- 用紙輪郭検出
- 四隅検出
- perspective transform
- 回転補正
- 基準サイズへの正規化
- 必要に応じてfine alignment


---

# 33. Phase 3

目的:

チェックボックス認識を成立させる。

まず以下を実装:

- 公演回
- 年齢

その後、

- きっかけ
- 宣伝媒体
- 予約のスムーズさ

へ拡張する。

この段階ではGoogle Cloud Vision APIを使用しない。


---

# 34. Phase 4

Google Cloud Vision APIを導入する。

最初はメッセージ欄だけOCRする。

読み取り結果をブラウザに表示する。


---

# 35. Phase 5

OCR対象を追加する。

- 名前
- 案内希望者名
- 郵便番号
- 住所
- メール
- 関係者名
- その他記述


---

# 36. Phase 6

確認画面を完成させる。

- 全フィールド編集
- 要確認表示
- validation


---

# 37. Phase 7

Google Sheets APIを導入する。

確認済みデータを
指定Spreadsheetへappendする。


---

# 38. Phase 8

スマートフォンのスキャンUXを改善する。

- カメラ
- 用紙枠
- 撮影
- プレビュー
- 撮り直し
- 次のアンケート


---

# 39. Phase 9

裏面読み取りを実装する。


---

# 40. Phase 10

実アンケート20〜30枚程度を使って精度調整する。

主な調整対象:

- template alignment
- checkbox threshold
- crop領域
- OCR前処理
- needsReview threshold


---

# 41. 最初の開発ゴール

最初から全機能を作らない。

まず以下の縦スライスを完成させる。

```text
記入済みアンケート画像
↓
ブラウザからアップロード
↓
FastAPI
↓
OpenCV
↓
用紙補正
↓
公演回チェック判定
↓
年齢チェック判定
↓
ブラウザに結果表示
```

この段階では、

- Google Cloud Vision API
- Google Sheets API
- 裏面
- 本格的なカメラUI

を実装しない。

この縦スライスが正常に動作してから次へ進む。


---

# 42. 将来拡張

MVP完成後、必要に応じて以下を検討する。

- 複数画像一括アップロード
- 一括OCR
- 確認待ち一覧
- PCからのドラッグ&ドロップ
- 複数公演テンプレート
- OCR provider切り替え
- Gemini/OpenAI等との認識精度比較
- CSV export
- PWA化


---

# 43. 開発上の原則

1. 固定レイアウトという利点を最大限利用する。
2. チェックボックスはOpenCVを優先する。
3. 手書き文字だけOCR APIを利用する。
4. 認識できない内容を推測しない。
5. 個人情報をログに残さない。
6. 元画像を永続保存しない。
7. API秘密情報をFrontendへ置かない。
8. 一度に全Phaseを実装しない。
9. 実データでthresholdを調整できる設計にする。
10. 約200枚を連続処理する人の操作負担を小さくする。