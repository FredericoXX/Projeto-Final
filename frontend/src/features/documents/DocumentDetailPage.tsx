import { useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import {
  useDeleteDocument,
  useDocument,
  useDocumentVersions,
  useReprocessVersion,
  useUpdateDocument,
  useUploadVersion,
} from './hooks';
import { downloadDocumentVersion } from '../../api/documents';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { EmptyState } from '../../components/feedback/EmptyState';
import { InlineError } from '../../components/feedback/InlineError';
import { OfficialBadge, ProcessingStatusBadge } from '../../components/common/StatusBadge';
import { ConfirmDialog } from '../../components/common/ConfirmDialog';
import { FormActions } from '../../components/forms/FormActions';
import { ApiError, errorTranslationKey } from '../../api/errors';
import { formatDate, formatDateTime, formatFileSize, safeHttpUrl } from '../../lib/format';
import type { UUID } from '../../types/api';
import type {
  DocumentRead,
  DocumentUpdateRequest,
  DocumentVersionRead,
} from '../../types/documents';

const ACCEPTED = '.pdf,.txt,.md';

interface EditFormState {
  title: string;
  description: string;
  language: string;
  source_url: string;
  official_source: boolean;
  is_active: boolean;
  valid_from: string;
  valid_until: string;
}

function editFormFromDocument(document: DocumentRead): EditFormState {
  return {
    title: document.title,
    description: document.description ?? '',
    language: document.language,
    source_url: document.source_url ?? '',
    official_source: document.official_source,
    is_active: document.is_active,
    valid_from: document.valid_from ?? '',
    valid_until: document.valid_until ?? '',
  };
}

export function DocumentDetailPage() {
  const { documentId = '' } = useParams();
  const { t, language } = useTranslation();
  const navigate = useNavigate();
  const documentQuery = useDocument(documentId);
  const versionsQuery = useDocumentVersions(documentId);
  const upload = useUploadVersion(documentId);
  const reprocess = useReprocessVersion(documentId);
  const updateMutation = useUpdateDocument(documentId);
  const deleteMutation = useDeleteDocument(documentId);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<UUID | null>(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<EditFormState | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
  const hasVersions = (versionsQuery.data?.items.length ?? 0) > 0;

  function startEditing() {
    setEditForm(editFormFromDocument(doc));
    setEditError(null);
    setEditing(true);
  }

  // Cancelar edição: descarta alterações locais e volta ao valor do backend.
  function cancelEditing() {
    setEditing(false);
    setEditForm(null);
    setEditError(null);
    updateMutation.reset();
  }

  function updateEditForm<K extends keyof EditFormState>(key: K, value: EditFormState[K]) {
    setEditForm((current) => (current ? { ...current, [key]: value } : current));
  }

  async function handleEditSave(event: FormEvent) {
    event.preventDefault();
    if (!editForm || updateMutation.isPending) return;
    setEditError(null);
    if (!editForm.title.trim()) {
      setEditError(t('form.required'));
      return;
    }
    if (editForm.source_url.trim() && !safeHttpUrl(editForm.source_url.trim())) {
      setEditError(t('form.invalidUrl'));
      return;
    }
    if (editForm.valid_from && editForm.valid_until && editForm.valid_from > editForm.valid_until) {
      setEditError(t('form.invalidDateRange'));
      return;
    }

    // Apenas campos do schema público; nada de institution_id, versões,
    // storage_path ou estado de processamento.
    const payload: DocumentUpdateRequest = {
      title: editForm.title.trim(),
      description: editForm.description.trim() ? editForm.description.trim() : null,
      source_url: editForm.source_url.trim() ? editForm.source_url.trim() : null,
      official_source: editForm.official_source,
      is_active: editForm.is_active,
      valid_from: editForm.valid_from ? editForm.valid_from : null,
      valid_until: editForm.valid_until ? editForm.valid_until : null,
    };
    // O idioma só é enviado enquanto for alterável (sem versões); depois
    // disso o campo fica desativado e o backend continua a validar.
    if (!hasVersions && editForm.language.trim()) {
      payload.language = editForm.language.trim();
    }

    try {
      await updateMutation.mutateAsync(payload);
      setEditing(false);
      setEditForm(null);
    } catch (error) {
      setEditError(t(errorTranslationKey(error)));
    }
  }

  async function handleDeleteConfirm() {
    if (deleteMutation.isPending) return;
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync();
      // Sucesso: sai do detalhe sem voltar a ler o documento eliminado.
      navigate('/admin/documents');
    } catch (error) {
      setDeleteDialogOpen(false);
      setDeleteError(
        error instanceof ApiError && error.status === 409
          ? t('error.documentReferenced')
          : t(errorTranslationKey(error)),
      );
    }
  }

  return (
    <div className="content-narrow stack">
      <div>
        <Link className="text-sm" to="/admin/documents">
          ‹ {t('documents.title')}
        </Link>
        <h1>{doc.title}</h1>
      </div>

      <section className="card">
        <div className="page-header" style={{ marginBottom: '0.75rem' }}>
          <h2 style={{ margin: 0 }}>{t('documents.metadata')}</h2>
          {!editing && (
            <button type="button" className="btn btn-secondary" onClick={startEditing}>
              {t('form.edit')}
            </button>
          )}
        </div>

        {editing && editForm ? (
          <form className="stack" onSubmit={handleEditSave}>
            {/* fieldset disabled: todos os campos ficam inertes durante a
                mutation, não apenas os botões. */}
            <fieldset className="form-fieldset form-grid" disabled={updateMutation.isPending}>
              <div className="field field-full">
                <label className="field-label" htmlFor="edit-title">
                  {t('documents.field.title')}
                </label>
                <input
                  id="edit-title"
                  className="input"
                  required
                  maxLength={255}
                  value={editForm.title}
                  onChange={(e) => updateEditForm('title', e.target.value)}
                />
              </div>
              <div className="field field-full">
                <label className="field-label" htmlFor="edit-description">
                  {t('documents.field.description')}
                </label>
                <textarea
                  id="edit-description"
                  className="textarea"
                  value={editForm.description}
                  onChange={(e) => updateEditForm('description', e.target.value)}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="edit-language">
                  {t('documents.field.language')}
                </label>
                <input
                  id="edit-language"
                  className="input"
                  value={editForm.language}
                  disabled={hasVersions}
                  aria-describedby={hasVersions ? 'edit-language-hint' : undefined}
                  onChange={(e) => updateEditForm('language', e.target.value)}
                />
                {hasVersions && (
                  <p id="edit-language-hint" className="text-sm text-muted">
                    {t('documents.languageLocked')}
                  </p>
                )}
              </div>
              <div className="field">
                <label className="field-label" htmlFor="edit-url">
                  {t('documents.field.sourceUrl')}
                </label>
                <input
                  id="edit-url"
                  className="input"
                  type="url"
                  value={editForm.source_url}
                  onChange={(e) => updateEditForm('source_url', e.target.value)}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="edit-valid-from">
                  {t('documents.field.validFrom')}
                </label>
                <input
                  id="edit-valid-from"
                  className="input"
                  type="date"
                  value={editForm.valid_from}
                  onChange={(e) => updateEditForm('valid_from', e.target.value)}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="edit-valid-until">
                  {t('documents.field.validUntil')}
                </label>
                <input
                  id="edit-valid-until"
                  className="input"
                  type="date"
                  value={editForm.valid_until}
                  onChange={(e) => updateEditForm('valid_until', e.target.value)}
                />
              </div>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={editForm.official_source}
                  onChange={(e) => updateEditForm('official_source', e.target.checked)}
                />
                {t('documents.field.official')}
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={editForm.is_active}
                  onChange={(e) => updateEditForm('is_active', e.target.checked)}
                />
                {t('documents.field.active')}
              </label>
            </fieldset>
            {editError && <InlineError message={editError} />}
            <FormActions pending={updateMutation.isPending} onCancel={cancelEditing} />
          </form>
        ) : (
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
        )}
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

      <section className="card danger-zone stack">
        <h2>{t('documents.dangerZone')}</h2>
        <p className="text-sm text-muted">
          {t('documents.deleteWarning')} {t('documents.deleteIrreversible')}
        </p>
        {deleteError && <InlineError message={deleteError} />}
        <div>
          <button
            type="button"
            className="btn btn-danger"
            disabled={deleteMutation.isPending}
            onClick={() => {
              setDeleteError(null);
              setDeleteDialogOpen(true);
            }}
          >
            {deleteMutation.isPending ? t('documents.deleting') : t('documents.delete')}
          </button>
        </div>
      </section>

      <ConfirmDialog
        open={deleteDialogOpen}
        title={t('documents.deleteConfirmTitle', { title: doc.title })}
        confirmLabel={
          deleteMutation.isPending ? t('documents.deleting') : t('documents.delete')
        }
        pending={deleteMutation.isPending}
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteDialogOpen(false)}
      >
        <p>{t('documents.deleteWarning')}</p>
        <p>
          <strong>{t('documents.deleteIrreversible')}</strong>
        </p>
      </ConfirmDialog>
    </div>
  );
}
