import { useEffect, useRef } from "react";
import { Glyph } from "./glyphs";

export type ToastItem = { id: number; message: string };

export function ErrorToast({ message, onClose }: { message: string; onClose: () => void }) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const timer = window.setTimeout(() => close.current(), 7000);
    return () => window.clearTimeout(timer);
  }, [message]);

  return (
    <div className="error-toast" role="alert">
      <span className="ic bad">{Glyph.errSmall}</span>
      <span className="toast-text">{message}</span>
      <button className="toast-close" type="button" aria-label="閉じる" onClick={onClose}>×</button>
    </div>
  );
}

export function ToastStack({ toasts, onClose }: { toasts: ToastItem[]; onClose: (id: number) => void }) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <ErrorToast key={toast.id} message={toast.message} onClose={() => onClose(toast.id)} />
      ))}
    </div>
  );
}
