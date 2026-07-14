import { useTranslation } from '../../i18n/useTranslation';

interface PaginationProps {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}

export function Pagination({ offset, limit, total, onChange }: PaginationProps) {
  const { t } = useTranslation();
  if (total <= limit) {
    return null;
  }
  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  return (
    <nav className="pagination" aria-label={t('nav.menu')}>
      <button
        type="button"
        className="btn btn-secondary"
        disabled={!canPrev}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        ‹
      </button>
      <span className="text-sm text-muted">
        {page} / {totalPages}
      </span>
      <button
        type="button"
        className="btn btn-secondary"
        disabled={!canNext}
        onClick={() => onChange(offset + limit)}
      >
        ›
      </button>
    </nav>
  );
}
