import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
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

  it('creates a document and opens its detail', async () => {
    tokenStorage.set('test-token');
    const user = userEvent.setup();
    renderApp('/admin/documents');

    await user.click(await screen.findByRole('button', { name: 'New document' }));
    await user.type(screen.getByLabelText('Title'), 'New Regulation');
    await user.click(screen.getByRole('button', { name: 'Create document' }));

    // Navigates to the document detail (upload section visible).
    expect(await screen.findByRole('heading', { name: 'Upload version' })).toBeInTheDocument();
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
