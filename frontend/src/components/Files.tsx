import { FileText, Paperclip, Trash2 } from "./icons";
import { useEffect, useState } from "react";
import { api, openFile } from "../api";
import type { Attachment } from "../types";
import { useToast } from "./Toast";

/** Image loaded through the authenticated API (plain <img src> cannot send the bearer token). */
export function AuthImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    api
      .blob(src)
      .then(({ blob }) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);
  if (failed) return <div className={`thumb-fallback ${className ?? ""}`}>Unavailable</div>;
  if (!url) return <div className={`thumb-fallback ${className ?? ""}`}>…</div>;
  return <img src={url} alt={alt} className={className} />;
}

export function AttachmentList({
  files,
  onRemove,
}: {
  files: Attachment[];
  onRemove?: (a: Attachment) => void;
}) {
  const toast = useToast();
  if (files.length === 0) return null;
  const open = (a: Attachment) => openFile(a.url).catch((e) => toast(e.message, "error"));
  return (
    <ul className="attachments">
      {files.map((a) => (
        <li key={a.id}>
          <button type="button" className="attachment" onClick={() => open(a)} title={`Open ${a.filename}`}>
            {a.content_type.startsWith("image/") ? (
              <AuthImage src={a.url} alt={a.filename} className="thumb" />
            ) : (
              <div className="thumb thumb-file">
                <FileText size={22} />
              </div>
            )}
            <span className="attachment-name">
              <Paperclip size={12} /> {a.filename}
            </span>
          </button>
          {onRemove && (
            <button type="button" className="icon-btn danger" onClick={() => onRemove(a)} aria-label={`Remove ${a.filename}`}>
              <Trash2 size={14} />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
