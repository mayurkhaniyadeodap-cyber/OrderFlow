import { FileUp, FileText, UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../components/Toast";
import { Alert, ErrorAlert, Section } from "../components/ui";
import type { OrderDetail } from "../types";

export function UploadPage() {
  const { config } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const maxMb = config?.max_upload_mb ?? 15;

  const choose = (f: File | undefined | null) => {
    setError(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf") && f.type !== "application/pdf") {
      setFile(null);
      setError({ message: `"${f.name}" is not a PDF. Only PDF purchase orders can be uploaded.` });
      return;
    }
    if (f.size > maxMb * 1024 * 1024) {
      setFile(null);
      setError({ message: `"${f.name}" is larger than ${maxMb} MB.` });
      return;
    }
    setFile(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    choose(e.dataTransfer.files?.[0]);
  };

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const order = await api.upload<OrderDetail>("/api/orders/upload", form);
      toast(`Draft created from ${file.name}`);
      navigate(`/orders/${order.id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Upload PO</h1>
          <p className="muted">Upload a purchase order PDF. Fields are extracted into a Draft for you to review and correct.</p>
        </div>
      </div>
      <Section title="Purchase order PDF" icon={<FileUp size={18} />}>
        <div
          className={`dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => input.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          aria-label="Choose a PDF file"
        >
          {file ? <FileText size={40} /> : <UploadCloud size={40} />}
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span className="muted">{(file.size / 1024).toFixed(0)} KB · click to choose another file</span>
            </>
          ) : (
            <>
              <strong>Drop a PDF here or click to browse</strong>
              <span className="muted">PDF only · up to {maxMb} MB</span>
            </>
          )}
          <input
            ref={input}
            type="file"
            accept="application/pdf,.pdf"
            hidden
            onChange={(e) => {
              choose(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>
        <ErrorAlert error={error} onClose={() => setError(null)} />
        <div className="form-actions">
          <button className="btn btn-primary" disabled={!file || busy} onClick={upload}>
            <FileUp size={16} /> {busy ? "Uploading and extracting…" : "Upload and extract"}
          </button>
        </div>
      </Section>
      <Alert tone="info" title="How extraction works">
        <ul className="bullets">
          <li>Text-based PDFs are read automatically; values are never guessed. Missing or doubtful values are flagged for review.</li>
          <li>Scanned / image-only PDFs have no text to read (OCR is not supported yet). A Draft is still created so you can type the details.</li>
          <li>The original PDF is stored with the order for reference by Sales and Printing.</li>
        </ul>
      </Alert>
    </div>
  );
}
