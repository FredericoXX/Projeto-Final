import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';
import { API } from '../../test/handlers';
import { makeVersion, sampleDocument } from '../../test/fixtures';
import { tokenStorage } from '../../api/token';

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

function installObjectUrlMocks() {
  const createObjectURL = vi.fn((object: Blob | MediaSource) => {
    void object;
    return 'blob:download-test';
  });
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: revokeObjectURL,
  });
  return { createObjectURL, revokeObjectURL };
}

afterEach(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: originalCreateObjectURL,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: originalRevokeObjectURL,
  });
  vi.restoreAllMocks();
});

describe('documents admin area', () => {
  it('lists documents for an admin', async () => {
    tokenStorage.set('test-token');
    renderApp('/admin/documents');
    expect(await screen.findAllByText('Academic Calendar')).not.toHaveLength(0);
  });

  it('creates a document with Save and opens its detail', async () => {
    tokenStorage.set('test-token');
    let createCalls = 0;
    server.use(
      http.post(`${API}/documents`, () => {
        createCalls += 1;
        return HttpResponse.json(sampleDocument, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/admin/documents');

    await user.click(await screen.findByRole('button', { name: 'New document' }));
    // O documento novo nasce como fonte oficial (official_source=true).
    expect(screen.getByRole('checkbox', { name: 'Official source' })).toBeChecked();
    await user.type(screen.getByLabelText('Title'), 'New Regulation');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    // Navigates to the document detail (upload section visible), one request.
    expect(await screen.findByRole('heading', { name: 'Upload version' })).toBeInTheDocument();
    expect(createCalls).toBe(1);
  });

  it('Save and New keeps the form open, resets fields and refocuses the title', async () => {
    tokenStorage.set('test-token');
    let createCalls = 0;
    server.use(
      http.post(`${API}/documents`, () => {
        createCalls += 1;
        return HttpResponse.json(sampleDocument, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/admin/documents');

    await user.click(await screen.findByRole('button', { name: 'New document' }));
    const title = screen.getByLabelText('Title');
    await user.type(title, 'First Regulation');
    await user.click(screen.getByRole('checkbox', { name: 'Official source' }));
    expect(screen.getByRole('checkbox', { name: 'Official source' })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Save and New' }));

    // Um único pedido; o formulário continua aberto, limpo, com os
    // valores padrão restaurados e o foco no título — sem navegação.
    await waitFor(() => expect(createCalls).toBe(1));
    expect(screen.getByLabelText('Title')).toHaveValue('');
    expect(screen.getByRole('checkbox', { name: 'Official source' })).toBeChecked();
    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveFocus());
    expect(screen.queryByRole('heading', { name: 'Upload version' })).not.toBeInTheDocument();
  });

  it('Cancel clears the form and closes it without calling the API', async () => {
    tokenStorage.set('test-token');
    let createCalls = 0;
    server.use(
      http.post(`${API}/documents`, () => {
        createCalls += 1;
        return HttpResponse.json(sampleDocument, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/admin/documents');

    await user.click(await screen.findByRole('button', { name: 'New document' }));
    await user.type(screen.getByLabelText('Title'), 'Discarded');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(createCalls).toBe(0);
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
    // Reabrir mostra o formulário limpo com os padrões.
    await user.click(screen.getByRole('button', { name: 'New document' }));
    expect(screen.getByLabelText('Title')).toHaveValue('');
    expect(screen.getByRole('checkbox', { name: 'Official source' })).toBeChecked();
  });

  it('keeps the typed data when creation fails', async () => {
    tokenStorage.set('test-token');
    server.use(
      http.post(`${API}/documents`, () =>
        HttpResponse.json({ detail: { code: 'resource_conflict', message: 'x' } }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/admin/documents');

    await user.click(await screen.findByRole('button', { name: 'New document' }));
    await user.type(screen.getByLabelText('Title'), 'Kept After Failure');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toHaveValue('Kept After Failure');
  });

  it('uploads a version as multipart FormData', async () => {
    tokenStorage.set('test-token');
    let contentType = '';
    server.use(
      http.post(`${API}/documents/:id/versions`, ({ request }) => {
        contentType = request.headers.get('content-type') ?? '';
        return HttpResponse.json(makeVersion(), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    const fileInput = await screen.findByLabelText('File (PDF, TXT, Markdown)');
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' });
    await user.upload(fileInput, file);
    await user.click(screen.getByRole('button', { name: 'Upload version' }));

    await waitFor(() => expect(contentType).toContain('multipart/form-data'));
  });

  it('shows a failed version with its error and a reprocess action', async () => {
    tokenStorage.set('test-token');
    server.use(
      http.get(`${API}/documents/:id/versions`, () =>
        HttpResponse.json({
          items: [
            makeVersion({
              processing_status: 'failed',
              processing_error: 'The file could not be decoded as UTF-8 text.',
              page_count: null,
            }),
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
    );
    renderApp(`/admin/documents/${sampleDocument.id}`);

    expect(
      await screen.findByText('The file could not be decoded as UTF-8 text.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reprocess' })).toBeInTheDocument();
  });

  it('reprocesses a failed version', async () => {
    tokenStorage.set('test-token');
    let reprocessed = false;
    server.use(
      http.get(`${API}/documents/:id/versions`, () =>
        HttpResponse.json({
          items: [makeVersion({ processing_status: 'failed', processing_error: 'boom' })],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
      http.post(`${API}/documents/:id/versions/:versionId/reprocess`, () => {
        reprocessed = true;
        return HttpResponse.json(makeVersion({ processing_status: 'processed' }));
      }),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Reprocess' }));
    await waitFor(() => expect(reprocessed).toBe(true));
  });

  it('shows a safe conflict message when reprocessing a referenced version', async () => {
    tokenStorage.set('test-token');
    server.use(
      http.get(`${API}/documents/:id/versions`, () =>
        HttpResponse.json({
          items: [makeVersion({ processing_status: 'failed', processing_error: 'boom' })],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
      http.post(`${API}/documents/:id/versions/:versionId/reprocess`, () =>
        HttpResponse.json(
          { detail: { code: 'resource_conflict', message: 'referenced' } },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Reprocess' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This version is referenced by persisted answers and cannot be reprocessed. Upload a new version.',
    );
  });

  it('downloads with authorization and always revokes the temporary URL', async () => {
    tokenStorage.set('test-token');
    const { createObjectURL, revokeObjectURL } = installObjectUrlMocks();
    let authorization: string | null = null;
    let downloadedFilename = '';
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloadedFilename = this.download;
    });
    server.use(
      http.get(`${API}/documents/:id/versions/:versionId/download`, ({ request }) => {
        authorization = request.headers.get('authorization');
        return new HttpResponse(new Blob(['document']), {
          headers: { 'content-type': 'application/pdf' },
        });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Download' }));
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:download-test'));
    expect(authorization).toBe('Bearer test-token');
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(createObjectURL.mock.calls[0][0]).toMatchObject({
      size: 13,
      type: 'application/pdf',
    });
    expect(downloadedFilename).toBe('calendar.pdf');
  });

  it('clears the session on a 401 download without creating a file', async () => {
    tokenStorage.set('test-token');
    const { createObjectURL } = installObjectUrlMocks();
    server.use(
      http.get(`${API}/documents/:id/versions/:versionId/download`, () =>
        HttpResponse.json(
          { detail: { code: 'authentication_required', message: 'expired' } },
          { status: 401 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Download' }));
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(tokenStorage.get()).toBeNull();
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it('does not download an error response as a file', async () => {
    tokenStorage.set('test-token');
    const { createObjectURL } = installObjectUrlMocks();
    server.use(
      http.get(`${API}/documents/:id/versions/:versionId/download`, () =>
        HttpResponse.json(
          { detail: { code: 'service_unavailable', message: 'temporary' } },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Download' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The generation service is currently unavailable.',
    );
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});

describe('document editing and deletion', () => {
  it('edits metadata sending only allowed fields and leaves edit mode', async () => {
    tokenStorage.set('test-token');
    let patchPayload: Record<string, unknown> | null = null;
    server.use(
      http.patch(`${API}/documents/:id`, async ({ request }) => {
        patchPayload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...sampleDocument, title: 'Edited Title' });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    const title = screen.getByLabelText('Title');
    await user.clear(title);
    await user.type(title, 'Edited Title');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('heading', { name: 'Edited Title' })).toBeInTheDocument();
    // Sai do modo de edição e nunca envia campos internos.
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(patchPayload).not.toBeNull();
    const sent = patchPayload as unknown as Record<string, unknown>;
    expect(sent.title).toBe('Edited Title');
    for (const forbidden of ['institution_id', 'created_by_user_id', 'storage_path', 'id']) {
      expect(sent).not.toHaveProperty(forbidden);
    }
  });

  it('disables the language field once versions exist and explains why', async () => {
    tokenStorage.set('test-token');
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    // O handler default devolve uma versão: idioma bloqueado.
    expect(screen.getByLabelText('Language')).toBeDisabled();
    expect(
      screen.getByText('The language can no longer be changed after versions have been uploaded.'),
    ).toBeInTheDocument();
  });

  it('cancel editing restores backend values without calling the API', async () => {
    tokenStorage.set('test-token');
    let patched = false;
    server.use(
      http.patch(`${API}/documents/:id`, () => {
        patched = true;
        return HttpResponse.json(sampleDocument);
      }),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    const title = screen.getByLabelText('Title');
    await user.clear(title);
    await user.type(title, 'Discarded change');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(patched).toBe(false);
    expect(
      await screen.findByRole('heading', { name: sampleDocument.title }),
    ).toBeInTheDocument();
  });

  it('deletes an uncited document after confirmation and returns to the list', async () => {
    tokenStorage.set('test-token');
    let deleteCalls = 0;
    server.use(
      http.delete(`${API}/documents/:id`, () => {
        deleteCalls += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Delete document' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent(`Delete "${sampleDocument.title}"?`);
    expect(dialog).toHaveTextContent('This action cannot be undone.');
    // O foco entra no Cancelar e o Escape fecha sem chamar a API.
    await user.keyboard('{Escape}');
    expect(deleteCalls).toBe(0);

    await user.click(screen.getByRole('button', { name: 'Delete document' }));
    const confirm = within(await screen.findByRole('dialog')).getByRole('button', {
      name: 'Delete document',
    });
    await user.click(confirm);

    // 204: volta à listagem de documentos.
    expect(await screen.findByRole('heading', { name: 'Documents' })).toBeInTheDocument();
    expect(deleteCalls).toBe(1);
  });

  it('shows the referenced-document guidance on 409 and keeps the detail visible', async () => {
    tokenStorage.set('test-token');
    server.use(
      http.delete(`${API}/documents/:id`, () =>
        HttpResponse.json(
          { detail: { code: 'resource_conflict', message: 'referenced' } },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Delete document' }));
    const confirm = within(await screen.findByRole('dialog')).getByRole('button', {
      name: 'Delete document',
    });
    await user.click(confirm);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Deactivate it to prevent its use in new answers.',
    );
    // O documento continua visível no detalhe.
    expect(screen.getByRole('heading', { name: sampleDocument.title })).toBeInTheDocument();
  });
});

describe('pending state disables the whole form', () => {
  it('disables every field while a document is being created', async () => {
    tokenStorage.set('test-token');
    const release: { create?: () => void } = {};
    server.use(
      http.post(`${API}/documents`, async () => {
        await new Promise<void>((resolve) => {
          release.create = resolve;
        });
        return HttpResponse.json(sampleDocument, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/admin/documents');

    await user.click(await screen.findByRole('button', { name: 'New document' }));
    await user.type(screen.getByLabelText('Title'), 'Pending Regulation');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    // Durante a mutation, o fieldset desativa TODOS os campos, não só os
    // botões.
    await waitFor(() => expect(screen.getByLabelText('Title')).toBeDisabled());
    expect(screen.getByLabelText('Description')).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Official source' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();

    release.create?.();
    // Conclui e navega para o detalhe.
    expect(await screen.findByRole('heading', { name: 'Upload version' })).toBeInTheDocument();
  });

  it('disables every field while document metadata is being saved', async () => {
    tokenStorage.set('test-token');
    const release: { patch?: () => void } = {};
    server.use(
      http.patch(`${API}/documents/:id`, async () => {
        await new Promise<void>((resolve) => {
          release.patch = resolve;
        });
        return HttpResponse.json(sampleDocument);
      }),
    );
    const user = userEvent.setup();
    renderApp(`/admin/documents/${sampleDocument.id}`);

    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByLabelText('Title')).toBeDisabled());
    expect(screen.getByLabelText('Source URL')).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Active' })).toBeDisabled();

    release.patch?.();
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Saving…' })).not.toBeInTheDocument(),
    );
  });
});
