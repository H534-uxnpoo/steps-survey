"use client";

import { ChangeEvent, useEffect, useRef, useState } from "react";

type FieldStatus = "selected" | "none" | "multiple" | "uncertain" | "recognized" | "unavailable";

type FieldResult = {
  value: string;
  confidence: number;
  needsReview: boolean;
  detailNeedsReview?: boolean;
  candidates: string[];
  status: FieldStatus;
};

type ScanResult = {
  scanId: string;
  fields: {
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
  needsReview: boolean;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type FieldKey = keyof ScanResult["fields"];

type SubmissionFields = Record<FieldKey, string>;

type FieldDefinition = {
  key: FieldKey;
  label: string;
  multiline?: boolean;
};

const fieldDefinitions: FieldDefinition[] = [
  { key: "performance", label: "公演回" },
  { key: "age", label: "年齢" },
  { key: "trigger", label: "きっかけ", multiline: true },
  { key: "media", label: "宣伝媒体", multiline: true },
  { key: "reservation", label: "予約のスムーズさ" },
  { key: "message", label: "メッセージ", multiline: true },
  { key: "name", label: "名前" },
  { key: "mailingName", label: "案内希望者名" },
  { key: "postalCode", label: "郵便番号" },
  { key: "address", label: "住所", multiline: true },
  { key: "email", label: "メアド" },
];

function responseErrorCode(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;

  const response = body as Record<string, unknown>;
  if (typeof response.code === "string") return response.code;

  if (response.detail && typeof response.detail === "object") {
    const detail = response.detail as Record<string, unknown>;
    if (typeof detail.code === "string") return detail.code;
  }

  return typeof response.detail === "string" ? response.detail : null;
}

function submissionErrorFor(body: unknown): string {
  switch (responseErrorCode(body)) {
    case "sheets_unavailable":
      return "Google Sheetsへの保存設定がまだ完了していません。";
    case "sheet_header_mismatch":
      return "スプレッドシートのヘッダーを確認できませんでした。登録は行っていません。";
    case "sheets_authentication_failed":
    case "sheets_auth_unavailable":
      return "Google Sheetsへの認証設定を確認してください。登録は行っていません。";
    case "submission_validation_error":
    case "validation_error":
      return "入力内容を確認してください。登録は行っていません。";
    default:
      return "Google Sheetsへ登録できませんでした。内容はこの画面に保持されています。時間をおいて再度お試しください。";
  }
}

function EditableResultItem({
  definition,
  field,
  value,
  onChange,
}: {
  definition: FieldDefinition;
  field: FieldResult;
  value: string;
  onChange: (value: string) => void;
}) {
  const inputId = `field-${definition.key}`;
  return (
    <div className={field.needsReview ? "edit-field review" : "edit-field"}>
      <label htmlFor={inputId}>{definition.label}</label>
      {definition.multiline ? (
        <textarea id={inputId} value={value} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input id={inputId} value={value} onChange={(event) => onChange(event.target.value)} />
      )}
      {field.status === "unavailable" && <p className="field-hint">OCRを実行できませんでした。原本を見て入力してください。</p>}
      {field.detailNeedsReview && <p className="field-hint">選択肢は読み取れましたが、付随する自由記述は要確認です。</p>}
      {field.needsReview && <p>要確認</p>}
    </div>
  );
}

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isScanning, setIsScanning] = useState(false);
  const [editedValues, setEditedValues] = useState<Partial<Record<FieldKey, string>>>({});
  const [cameraOpen, setCameraOpen] = useState(false);
  const [preview, setPreview] = useState<{ file: File; url: string } | null>(null);
  const [hasConfirmedSubmission, setHasConfirmedSubmission] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionSucceeded, setSubmissionSucceeded] = useState(false);
  const [submissionError, setSubmissionError] = useState("");

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraOpen(false);
  }

  useEffect(() => {
    if (cameraOpen && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [cameraOpen]);

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview.url);
  }, [preview]);

  function selectPreview(file: File) {
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      setErrorMessage("JPEGまたはPNG形式の画像を選択してください。");
      return;
    }
    setErrorMessage("");
    setPreview({ file, url: URL.createObjectURL(file) });
  }

  function resetForNextSurvey() {
    stopCamera();
    setResult(null);
    setEditedValues({});
    setPreview(null);
    setErrorMessage("");
    setHasConfirmedSubmission(false);
    setIsSubmitting(false);
    setSubmissionSucceeded(false);
    setSubmissionError("");
    if (inputRef.current) inputRef.current.value = "";
  }

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setErrorMessage("このブラウザではカメラを利用できません。写真から選択してください。");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" } },
      });
      streamRef.current = stream;
      setErrorMessage("");
      setCameraOpen(true);
    } catch {
      setErrorMessage("カメラを起動できませんでした。許可設定を確認するか、写真から選択してください。");
    }
  }

  function capturePhoto() {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) {
      setErrorMessage("カメラ映像を取得できませんでした。撮り直してください。");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) {
        setErrorMessage("撮影画像を作成できませんでした。撮り直してください。");
        return;
      }
      stopCamera();
      selectPreview(new File([blob], "survey-camera.jpg", { type: "image/jpeg" }));
    }, "image/jpeg", 0.92);
  }

  async function upload(file: File) {
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      setErrorMessage("JPEGまたはPNG形式の画像を選択してください。");
      return;
    }
    setIsScanning(true);
    setErrorMessage("");
    setResult(null);
    setEditedValues({});
    setHasConfirmedSubmission(false);
    setIsSubmitting(false);
    setSubmissionSucceeded(false);
    setSubmissionError("");
    const formData = new FormData();
    formData.append("image", file);

    try {
      const response = await fetch(`${API_BASE_URL}/api/scan/front`, {
        method: "POST",
        body: formData,
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setErrorMessage(body?.detail ?? "読み取りに失敗しました。画像を確認して再度お試しください。");
        return;
      }
      const scanResult = body as ScanResult;
      setResult(scanResult);
      setEditedValues(
        Object.fromEntries(fieldDefinitions.map(({ key }) => [key, scanResult.fields[key].value]))
      );
      setPreview(null);
    } catch {
      setErrorMessage("サーバーに接続できません。バックエンドが起動しているか確認してください。");
    } finally {
      setIsScanning(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) selectPreview(file);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function submitConfirmedValues() {
    if (!result || !hasConfirmedSubmission || isSubmitting || submissionSucceeded) return;

    const fields = Object.fromEntries(
      fieldDefinitions.map(({ key }) => [key, editedValues[key] ?? ""])
    ) as SubmissionFields;

    setIsSubmitting(true);
    setSubmissionError("");

    try {
      const response = await fetch(`${API_BASE_URL}/api/submissions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      const body = await response.json().catch(() => null);

      if (!response.ok || body?.success !== true) {
        setSubmissionError(submissionErrorFor(body));
        return;
      }

      setSubmissionSucceeded(true);
    } catch {
      setSubmissionError("サーバーに接続できません。内容はこの画面に保持されています。接続を確認して再度お試しください。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main>
      <section className="card">
        <p className="eyebrow">STEPS Musical Company</p>
        <h1>アンケート読取</h1>
        <p className="lead">カメラで撮影、または写真を選択して、プレビューを確認してから読み取ります。</p>
        <input
          ref={inputRef}
          id="survey-image"
          className="visually-hidden"
          type="file"
          accept="image/jpeg,image/png"
          onChange={onFileChange}
          disabled={isScanning || cameraOpen}
        />
        {!result && !preview && !cameraOpen && (
          <div className="source-actions">
            <button type="button" onClick={() => void startCamera()} disabled={isScanning}>カメラを起動</button>
            <button type="button" className="secondary-button" onClick={() => inputRef.current?.click()} disabled={isScanning}>写真から選択</button>
          </div>
        )}
        {cameraOpen && (
          <div className="camera-panel">
            <video ref={videoRef} autoPlay playsInline muted aria-label="カメラプレビュー" />
            <div className="source-actions">
              <button type="button" onClick={capturePhoto}>撮影する</button>
              <button type="button" className="secondary-button" onClick={stopCamera}>キャンセル</button>
            </div>
          </div>
        )}
        {preview && (
          <div className="capture-preview">
            <img src={preview.url} alt="撮影したアンケートのプレビュー" />
            <div className="source-actions">
              <button type="button" onClick={() => void upload(preview.file)} disabled={isScanning}>{isScanning ? "読み取り中…" : "この画像を使用"}</button>
              <button type="button" className="secondary-button" onClick={() => setPreview(null)} disabled={isScanning}>撮り直す</button>
            </div>
          </div>
        )}
        <p className="hint">JPEG・PNG、12MB以下。補正に失敗した場合は、アンケート全体が画面に入るように撮り直してください。画像は保存されません。</p>
        {errorMessage && <p className="error" role="alert">{errorMessage}</p>}
      </section>

      {result && (
        <section className="card results" aria-live="polite">
          {submissionSucceeded ? (
            <div className="submission-success">
              <h2>登録しました</h2>
              <p>Google Sheetsへ1件を登録しました。</p>
              <button type="button" onClick={resetForNextSurvey}>次のアンケートを読み取る</button>
            </div>
          ) : (
            <>
              <h2>確認・修正</h2>
              {result.needsReview && <p className="review-summary">要確認の項目を先頭に表示しています。原本を見て修正してください。</p>}
              <div className="edit-list">
                {[...fieldDefinitions]
                  .sort((left, right) => Number(result.fields[right.key].needsReview) - Number(result.fields[left.key].needsReview))
                  .map((definition) => (
                    <EditableResultItem
                      key={definition.key}
                      definition={definition}
                      field={result.fields[definition.key]}
                      value={editedValues[definition.key] ?? ""}
                      onChange={(value) => {
                        setEditedValues((current) => ({ ...current, [definition.key]: value }));
                        setHasConfirmedSubmission(false);
                        setSubmissionError("");
                      }}
                    />
                  ))}
              </div>
              <p className="local-only">修正内容はこの画面内でのみ保持されます。内容を確認してから、下の操作でGoogle Sheetsへ登録してください。</p>
              {result.needsReview && <p className="review-summary">要確認の項目が残っています。原本を確認したうえで登録してください。</p>}
              <label className="submission-confirmation">
                <input
                  type="checkbox"
                  checked={hasConfirmedSubmission}
                  disabled={isSubmitting}
                  onChange={(event) => setHasConfirmedSubmission(event.target.checked)}
                />
                内容を確認しました
              </label>
              <p className="submission-hint">確認後にのみ登録できます。登録されるのは、この画面で編集した11項目です。</p>
              {submissionError && <p className="error" role="alert">{submissionError}</p>}
              <button
                type="button"
                onClick={() => void submitConfirmedValues()}
                disabled={!hasConfirmedSubmission || isSubmitting}
              >
                {isSubmitting ? "登録中…" : "スプレッドシートに登録"}
              </button>
            </>
          )}
        </section>
      )}
    </main>
  );
}
