import { useEffect, useId, useRef, type ReactNode } from 'react';
import { useTranslation } from '../../i18n/useTranslation';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  pending: boolean;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])';

// Diálogo de confirmação acessível: foco entra no Cancelar e fica retido
// no modal (Tab cicla), Escape fecha, o foco regressa ao elemento
// anterior ao fechar, as ações são desativadas durante o pedido e o
// perigo é comunicado por texto — nunca apenas por cor.
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  pending,
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    return () => {
      previousFocusRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !pending) {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== 'Tab') {
        return;
      }
      // Focus trap: Tab e Shift+Tab ciclam dentro do diálogo.
      const container = dialogRef.current;
      if (!container) {
        return;
      }
      const focusable = Array.from(
        container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !container.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !container.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, pending, onCancel]);

  if (!open) {
    return null;
  }

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialogRef}
        className="dialog card stack"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h2 id={titleId}>{title}</h2>
        <div>{children}</div>
        <div className="composer-row">
          <button
            ref={cancelRef}
            type="button"
            className="btn btn-secondary"
            disabled={pending}
            onClick={onCancel}
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
            disabled={pending}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
