import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import { useCreateDocument, useDocuments } from './hooks';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { EmptyState } from '../../components/feedback/EmptyState';
import { InlineError } from '../../components/feedback/InlineError';
import { Pagination } from '../../components/common/Pagination';
import { OfficialBadge } from '../../components/common/StatusBadge';
import { errorTranslationKey } from '../../api/errors';
import { formatDate, formatDateTime, safeHttpUrl } from '../../lib/format';
import type { DocumentCreateRequest, DocumentFilters } from '../../types/documents';

const PAGE_SIZE = 20;

type TriState = 'all' | 'true' | 'false';

function toBool(value: TriState): boolean | undefined {
  if (value === 'all') return undefined;
  return value === 'true';
}

export function DocumentsPage() {
  const { t, language } = useTranslation();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [activeFilter, setActiveFilter] = useState<TriState>('all');
  const [officialFilter, setOfficialFilter] = useState<TriState>('all');
  const [languageFilter, setLanguageFilter] = useState('');
  const [creating, setCreating] = useState(false);

  const filters: DocumentFilters = {
    is_active: toBool(activeFilter),
    official_source: toBool(officialFilter),
    language: languageFilter.trim() || undefined,
  };

  const documentsQuery = useDocuments(filters, offset);
  const createMutation = useCreateDocument();

  const [form, setForm] = useState({
    title: '',
    description: '',
    language: '',
    source_url: '',
    official_source: false,
    valid_from: '',
    valid_until: '',
  });
  const [formError, setFormError] = useState<string | null>(null);

  function updateForm<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormError(null);

    if (!form.title.trim()) {
      setFormError(t('form.required'));
      return;
    }
    if (form.source_url.trim() && !safeHttpUrl(form.source_url.trim())) {
      setFormError(t('form.invalidUrl'));
      return;
    }
    if (form.valid_from && form.valid_until && form.valid_from > form.valid_until) {
      setFormError(t('form.invalidDateRange'));
      return;
    }

    const payload: DocumentCreateRequest = {
      title: form.title.trim(),
      official_source: form.official_source,
    };
    if (form.description.trim()) payload.description = form.description.trim();
    if (form.language.trim()) payload.language = form.language.trim();
    if (form.source_url.trim()) payload.source_url = form.source_url.trim();
    if (form.valid_from) payload.valid_from = form.valid_from;
    if (form.valid_until) payload.valid_until = form.valid_until;

    try {
      const created = await createMutation.mutateAsync(payload);
      navigate(`/admin/documents/${created.id}`);
    } catch (error) {
      setFormError(t(errorTranslationKey(error)));
    }
  }

  return (
    <div className="content-narrow">
      <div className="page-header">
        <h1>{t('documents.title')}</h1>
        <button type="button" className="btn btn-primary" onClick={() => setCreating((v) => !v)}>
          {t('documents.new')}
        </button>
      </div>

      {creating && (
        <form className="card stack" onSubmit={handleCreate} style={{ marginBottom: '1.5rem' }}>
          <h2>{t('documents.create')}</h2>
          <div className="form-grid">
            <div className="field field-full">
              <label className="field-label" htmlFor="doc-title">
                {t('documents.field.title')}
              </label>
              <input
                id="doc-title"
                className="input"
                required
                maxLength={255}
                value={form.title}
                onChange={(e) => updateForm('title', e.target.value)}
              />
            </div>
            <div className="field field-full">
              <label className="field-label" htmlFor="doc-description">
                {t('documents.field.description')}
              </label>
              <textarea
                id="doc-description"
                className="textarea"
                value={form.description}
                onChange={(e) => updateForm('description', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="doc-language">
                {t('documents.field.language')}
              </label>
              <input
                id="doc-language"
                className="input"
                placeholder="pt"
                value={form.language}
                onChange={(e) => updateForm('language', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="doc-url">
                {t('documents.field.sourceUrl')}
              </label>
              <input
                id="doc-url"
                className="input"
                type="url"
                value={form.source_url}
                onChange={(e) => updateForm('source_url', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="doc-valid-from">
                {t('documents.field.validFrom')}
              </label>
              <input
                id="doc-valid-from"
                className="input"
                type="date"
                value={form.valid_from}
                onChange={(e) => updateForm('valid_from', e.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="doc-valid-until">
                {t('documents.field.validUntil')}
              </label>
              <input
                id="doc-valid-until"
                className="input"
                type="date"
                value={form.valid_until}
                onChange={(e) => updateForm('valid_until', e.target.value)}
              />
            </div>
            <label className="checkbox-field field-full">
              <input
                type="checkbox"
                checked={form.official_source}
                onChange={(e) => updateForm('official_source', e.target.checked)}
              />
              {t('documents.field.official')}
            </label>
          </div>
          {formError && <InlineError message={formError} />}
          <div className="composer-row">
            <button type="submit" className="btn btn-primary" disabled={createMutation.isPending}>
              {createMutation.isPending ? t('documents.creating') : t('documents.create')}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setCreating(false)}>
              {t('common.cancel')}
            </button>
          </div>
        </form>
      )}

      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="filter-active">
              {t('documents.filter.active')}
            </label>
            <select
              id="filter-active"
              className="select"
              value={activeFilter}
              onChange={(e) => {
                setActiveFilter(e.target.value as TriState);
                setOffset(0);
              }}
            >
              <option value="all">{t('documents.filter.all')}</option>
              <option value="true">{t('common.yes')}</option>
              <option value="false">{t('common.no')}</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="filter-official">
              {t('documents.filter.official')}
            </label>
            <select
              id="filter-official"
              className="select"
              value={officialFilter}
              onChange={(e) => {
                setOfficialFilter(e.target.value as TriState);
                setOffset(0);
              }}
            >
              <option value="all">{t('documents.filter.all')}</option>
              <option value="true">{t('common.yes')}</option>
              <option value="false">{t('common.no')}</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="filter-language">
              {t('documents.filter.language')}
            </label>
            <input
              id="filter-language"
              className="input"
              placeholder="pt"
              value={languageFilter}
              onChange={(e) => {
                setLanguageFilter(e.target.value);
                setOffset(0);
              }}
            />
          </div>
        </div>
      </div>

      {documentsQuery.isPending && <LoadingState />}
      {documentsQuery.isError && (
        <ErrorState error={documentsQuery.error} onRetry={() => documentsQuery.refetch()} />
      )}
      {documentsQuery.isSuccess &&
        (documentsQuery.data.items.length === 0 ? (
          <EmptyState message={t('documents.empty')} />
        ) : (
          <>
            <div className="list">
              {documentsQuery.data.items.map((document) => (
                <button
                  key={document.id}
                  type="button"
                  className="list-row"
                  onClick={() => navigate(`/admin/documents/${document.id}`)}
                >
                  <span className="list-row-main">
                    <span className="list-row-title">{document.title}</span>
                    <span className="list-row-meta">
                      <OfficialBadge official={document.official_source} />
                      <span>{document.language}</span>
                      {!document.is_active && (
                        <span className="badge badge--neutral">{t('common.no')}</span>
                      )}
                      {document.valid_until && (
                        <span>
                          {t('documents.field.validUntil')}:{' '}
                          {formatDate(document.valid_until, language)}
                        </span>
                      )}
                      <span>
                        {t('documents.field.updatedAt')}:{' '}
                        {formatDateTime(document.updated_at, language)}
                      </span>
                    </span>
                  </span>
                  <span aria-hidden="true">›</span>
                </button>
              ))}
            </div>
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={documentsQuery.data.total}
              onChange={setOffset}
            />
          </>
        ))}
    </div>
  );
}
