import { useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import { useDocument, useDocumentVersions, useReprocessVersion, useUploadVersion } from './hooks';
import { downloadDocumentVersion } from '../../api/documents';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { EmptyState } from '../../components/feedback/EmptyState';
import { InlineError } from '../../components/feedback/InlineError';
import { OfficialBadge, ProcessingStatusBadge } from '../../components/common/StatusBadge';
import { ApiError, errorTranslationKey } from '../../api/errors';
import { formatDate, formatDateTime, formatFileSize } from '../../lib/format';
import type { UUID } from '../../types/api';
import type { DocumentVersionRead } from '../../types/documents';

const ACCEPTED = '.pdf,.txt,.md';

export function DocumentDetailPage() {
  const { documentId = '' } = useParams();
  const { t, language } = useTranslation();
  const documentQuery = useDocument(documentId);
  const versionsQuery = useDocumentVersions(documentId);
  const upload = useUploadVersion(documentId);
  const reprocess = useReprocessVersion(documentId);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<UUID | null>(null);

  async function handleUpload() {
    if (!selectedFile) return;
    setUploadError(null);
    try {
      await upload.mutateAsync(selectedFile);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (error) {
      setUploadError(t(errorTranslationKey(error)));
    }
  }

  async function handleReprocess(versionId: UUID) {
    setActionError(null);
    try {
      await reprocess.mutateAsync(versionId);
    } catch (error) {
      setActionError(
        error instanceof ApiError && error.status === 409
          ? t('error.versionReferenced')
          : t(errorTranslationKey(error)),
      );
    }
  }

  async function handleDownload(version: DocumentVersionRead) {
    setActionError(null);
    setDownloadingId(version.id);
    let objectUrl: string | null = null;
    try {
      const blob = await downloadDocumentVersion(documentId, version.id);
      objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = version.original_filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      setActionError(t(errorTranslationKey(error)));
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setDownloadingId(null);
    }
  }

  if (documentQuery.isPending) return <LoadingState />;
  if (documentQuery.isError) {
    return (
      <div className="content-narrow">
        <ErrorState error={documentQuery.error} />
        <Link className="btn btn-secondary" to="/admin/documents">
          {t('common.back')}
        </Link>
      </div>
    );
  }

  const doc = documentQuery.data;

  return (
    <div className="content-narrow stack">
      <div>
        <Link className="text-sm" to="/admin/documents">
          ‹ {t('documents.title')}
        </Link>
        <h1>{doc.title}</h1>
      </div>

      <section className="card">
        <h2>{t('documents.metadata')}</h2>
        <dl className="definition-grid">
          <dt>{t('documents.field.language')}</dt>
          <dd>{doc.language}</dd>
          <dt>{t('documents.field.official')}</dt>
          <dd>
            <OfficialBadge official={doc.official_source} />
          </dd>
          <dt>{t('documents.field.active')}</dt>
          <dd>{doc.is_active ? t('common.yes') : t('common.no')}</dd>
          {doc.description && (
            <>
              <dt>{t('documents.field.description')}</dt>
              <dd>{doc.description}</dd>
            </>
          )}
          <dt>{t('documents.field.validFrom')}</dt>
          <dd>{doc.valid_from ? formatDate(doc.valid_from, language) : t('common.none')}</dd>
          <dt>{t('documents.field.validUntil')}</dt>
          <dd>{doc.valid_until ? formatDate(doc.valid_until, language) : t('common.none')}</dd>
          <dt>{t('documents.field.updatedAt')}</dt>
          <dd>{formatDateTime(doc.updated_at, language)}</dd>
        </dl>
      </section>

      <section className="card stack">
        <h2>{t('documents.upload')}</h2>
        <div className="field">
          <label className="field-label" htmlFor="version-file">
            {t('documents.uploadFile')}
          </label>
          <input
            id="version-file"
            ref={fileInputRef}
            className="input"
            type="file"
            accept={ACCEPTED}
            onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
          />
        </div>
        {selectedFile && (
          <p className="text-sm text-muted">
            {t('documents.selectedFile', {
              name: selectedFile.name,
              size: formatFileSize(selectedFile.size, language),
            })}
          </p>
        )}
        {uploadError && <InlineError message={uploadError} />}
        <div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!selectedFile || upload.isPending}
            onClick={handleUpload}
          >
            {upload.isPending ? t('documents.uploading') : t('documents.upload')}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>{t('documents.versions')}</h2>
        {actionError && <InlineError message={actionError} />}
        {versionsQuery.isPending && <LoadingState />}
        {versionsQuery.isError && (
          <ErrorState error={versionsQuery.error} onRetry={() => versionsQuery.refetch()} />
        )}
        {versionsQuery.isSuccess &&
          (versionsQuery.data.items.length === 0 ? (
            <EmptyState message={t('documents.versionsEmpty')} />
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t('documents.version.number')}</th>
                    <th>{t('documents.version.filename')}</th>
                    <th>{t('documents.version.size')}</th>
                    <th>{t('documents.version.status')}</th>
                    <th>{t('documents.version.pages')}</th>
                    <th>{t('documents.version.createdAt')}</th>
                    <th aria-label={t('common.open')} />
                  </tr>
                </thead>
                <tbody>
                  {versionsQuery.data.items.map((version) => (
                    <tr key={version.id}>
                      <td>{version.version_number}</td>
                      <td>{version.original_filename}</td>
                      <td>{formatFileSize(version.size_bytes, language)}</td>
                      <td>
                        <ProcessingStatusBadge status={version.processing_status} />
                        {version.processing_status === 'failed' && version.processing_error && (
                          <div className="inline-error text-sm">{version.processing_error}</div>
                        )}
                      </td>
                      <td>{version.page_count ?? t('common.none')}</td>
                      <td>{formatDateTime(version.created_at, language)}</td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                          {version.processing_status === 'failed' && (
                            <button
                              type="button"
                              className="btn btn-secondary"
                              disabled={reprocess.isPending}
                              onClick={() => handleReprocess(version.id)}
                            >
                              {reprocess.isPending
                                ? t('documents.reprocessing')
                                : t('documents.reprocess')}
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-ghost"
                            disabled={downloadingId === version.id}
                            onClick={() => handleDownload(version)}
                          >
                            {downloadingId === version.id
                              ? t('documents.downloading')
                              : t('documents.download')}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
      </section>
    </div>
  );
}
