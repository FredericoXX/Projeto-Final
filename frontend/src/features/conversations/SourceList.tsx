import { useState } from 'react';
import { useTranslation } from '../../i18n/useTranslation';
import type { MessageSourceRead } from '../../types/conversations';
import { OfficialBadge } from '../../components/common/StatusBadge';
import { formatDate, safeHttpUrl } from '../../lib/format';

export function SourceList({ sources }: { sources: MessageSourceRead[] }) {
  const { t, language } = useTranslation();
  const [open, setOpen] = useState(false);

  if (sources.length === 0) {
    return null;
  }

  const ordered = [...sources].sort((a, b) => a.citation_index - b.citation_index);

  return (
    <section className="sources">
      <button
        type="button"
        className="sources-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? t('sources.hide') : t('sources.show', { count: sources.length })}
      </button>
      {open && (
        <ol style={{ listStyle: 'none', margin: '0.5rem 0 0', padding: 0 }}>
          {ordered.map((source, index) => {
            const href = safeHttpUrl(source.source_url);
            return (
              <li key={source.id} className="source-item">
                <div className="source-head">
                  <span className="source-index">[{index + 1}]</span>
                  <span>{source.document_title}</span>
                  <OfficialBadge official={source.official_source} />
                </div>
                <div className="list-row-meta">
                  <span>
                    {t('sources.language')}: {source.language}
                  </span>
                  {source.valid_from && (
                    <span>
                      {t('sources.validFrom')}: {formatDate(source.valid_from, language)}
                    </span>
                  )}
                  {source.valid_until && (
                    <span>
                      {t('sources.validUntil')}: {formatDate(source.valid_until, language)}
                    </span>
                  )}
                </div>
                {href && (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {t('sources.open')}
                  </a>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
