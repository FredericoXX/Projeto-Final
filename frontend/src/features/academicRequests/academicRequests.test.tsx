import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';
import { API } from '../../test/handlers';
import {
  academicRequestDetail,
  academicRequestList,
  adminUser,
  studentUser,
} from '../../test/fixtures';
import { tokenStorage } from '../../api/token';
import { LANGUAGE_STORAGE_KEY } from '../../i18n';
import type { AcademicRequestAccessRead } from '../../types/academicRequests';

const AVAILABLE_SIMULATED: AcademicRequestAccessRead = {
  available: true,
  reason: 'available',
  simulated: true,
};

// Registado por último para ter precedência: o padrão /academic-requests/:requestId
// também corresponderia a /academic-requests/access.
function signInAsStudent(access: AcademicRequestAccessRead = AVAILABLE_SIMULATED) {
  tokenStorage.set('test-token');
  server.use(
    http.get(`${API}/auth/me`, () => HttpResponse.json(studentUser)),
    http.get(`${API}/academic-requests/access`, () => HttpResponse.json(access)),
  );
}

describe('academic requests area', () => {
  it('shows the navigation entry to a linked student', async () => {
    signInAsStudent();
    renderApp('/app/conversations');
    expect(await screen.findByRole('link', { name: 'My requests' })).toBeInTheDocument();
  });

  it('hides the navigation entry when the integration is not configured', async () => {
    signInAsStudent({ available: false, reason: 'not_configured', simulated: false });
    renderApp('/app/conversations');
    await screen.findByText('Academic matters');
    expect(screen.queryByRole('link', { name: 'My requests' })).not.toBeInTheDocument();
  });

  it('never asks for access on behalf of an account without the permission', async () => {
    let accessCalls = 0;
    tokenStorage.set('test-token');
    server.use(
      http.get(`${API}/auth/me`, () => HttpResponse.json(adminUser)),
      http.get(`${API}/academic-requests/access`, () => {
        accessCalls += 1;
        return HttpResponse.json(AVAILABLE_SIMULATED);
      }),
    );
    renderApp('/app/conversations');
    await screen.findByText('Academic matters');
    expect(screen.queryByRole('link', { name: 'My requests' })).not.toBeInTheDocument();
    expect(accessCalls).toBe(0);
  });

  it('denies the area to an account without the permission', async () => {
    tokenStorage.set('test-token');
    server.use(http.get(`${API}/auth/me`, () => HttpResponse.json(adminUser)));
    renderApp('/app/academic-requests');
    expect(
      await screen.findByText('You do not have permission to access this area.'),
    ).toBeInTheDocument();
  });

  it('lists own requests with the official status as received and identifies the demo', async () => {
    signInAsStudent();
    server.use(
      http.get(`${API}/academic-requests`, () => HttpResponse.json(academicRequestList)),
    );
    renderApp('/app/academic-requests');

    expect(await screen.findByText('Certidão de matrícula')).toBeInTheDocument();
    expect(screen.getByText('Em apreciação')).toBeInTheDocument();
    expect(screen.getByText('Emitida')).toBeInTheDocument();
    const notice = screen.getByRole('note');
    expect(within(notice).getByText('Demo')).toBeInTheDocument();
    expect(notice).toHaveTextContent('synthetic demonstration data');
    expect(screen.getByText(/Source: institutional academic system/)).toBeInTheDocument();
  });

  it('does not show the demo notice when the source is not simulated', async () => {
    signInAsStudent({ available: true, reason: 'available', simulated: false });
    server.use(
      http.get(`${API}/academic-requests`, () =>
        HttpResponse.json({
          ...academicRequestList,
          provenance: { ...academicRequestList.provenance, simulated: false },
        }),
      ),
    );
    renderApp('/app/academic-requests');
    await screen.findByText('Certidão de matrícula');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('shows a clear empty state', async () => {
    signInAsStudent();
    server.use(
      http.get(`${API}/academic-requests`, () =>
        HttpResponse.json({
          outcome: 'no_data',
          items: [],
          provenance: { ...academicRequestList.provenance, access_result: 'no_data' },
        }),
      ),
    );
    renderApp('/app/academic-requests');
    expect(
      await screen.findByText('There are no academic requests associated with your account.'),
    ).toBeInTheDocument();
  });

  it('explains that an unlinked account cannot consult requests, without querying them', async () => {
    // Nenhum handler para /academic-requests: um pedido inesperado falharia o teste.
    signInAsStudent({ available: false, reason: 'not_linked', simulated: true });
    renderApp('/app/academic-requests');
    expect(
      await screen.findByText(/Your account is not yet linked to an academic record/),
    ).toBeInTheDocument();
  });

  it('explains that the lookup is unavailable when the integration is disabled', async () => {
    signInAsStudent({ available: false, reason: 'not_configured', simulated: false });
    renderApp('/app/academic-requests');
    expect(
      await screen.findByText('Academic request lookup is not available in this installation.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Certidão de matrícula')).not.toBeInTheDocument();
  });

  it('distinguishes a technical failure of the academic system', async () => {
    signInAsStudent();
    server.use(
      http.get(`${API}/academic-requests`, () =>
        HttpResponse.json(
          {
            detail: {
              code: 'institutional_integration_unavailable',
              message: 'The institutional service is temporarily unavailable.',
            },
          },
          { status: 502 },
        ),
      ),
    );
    renderApp('/app/academic-requests');
    expect(
      await screen.findByText(
        'The academic system is temporarily unavailable. Please try again later.',
      ),
    ).toBeInTheDocument();
    // Nunca confundido com o serviço de geração de respostas.
    expect(screen.queryByText(/Answer generation failed/)).not.toBeInTheDocument();
  });

  it('reports a source denial as an authorisation problem', async () => {
    signInAsStudent();
    server.use(
      http.get(`${API}/academic-requests`, () =>
        HttpResponse.json(
          { detail: { code: 'institutional_access_denied', message: 'x' } },
          { status: 403 },
        ),
      ),
    );
    renderApp('/app/academic-requests');
    expect(
      await screen.findByText('You are not authorised to consult these academic records.'),
    ).toBeInTheDocument();
  });

  it('opens the detail and shows the next step only when the source provides it', async () => {
    server.use(
      http.get(`${API}/academic-requests`, () => HttpResponse.json(academicRequestList)),
      http.get(`${API}/academic-requests/:requestId`, () =>
        HttpResponse.json(academicRequestDetail),
      ),
    );
    signInAsStudent();
    const user = userEvent.setup();
    renderApp('/app/academic-requests');

    await user.click(await screen.findByText('Creditação de unidades curriculares'));

    expect(await screen.findByText('REQ-0001-B')).toBeInTheDocument();
    expect(screen.getByText(/shown as received from the academic system/)).toBeInTheDocument();
    expect(screen.queryByText('Next step given by the source')).not.toBeInTheDocument();
  });

  it('shows the next step on a detail that has one', async () => {
    server.use(
      http.get(`${API}/academic-requests/:requestId`, () =>
        HttpResponse.json({ ...academicRequestDetail, item: academicRequestList.items[0] }),
      ),
    );
    signInAsStudent();
    renderApp('/app/academic-requests/REQ-0001-A');
    expect(await screen.findByText('Next step given by the source')).toBeInTheDocument();
    expect(screen.getByText('Disponível para descarga no portal académico.')).toBeInTheDocument();
  });

  it('shows a not-found detail without revealing anything else', async () => {
    server.use(
      http.get(`${API}/academic-requests/:requestId`, () =>
        HttpResponse.json(
          { detail: { code: 'resource_not_found', message: 'Academic request not found.' } },
          { status: 404 },
        ),
      ),
    );
    signInAsStudent();
    renderApp('/app/academic-requests/REQ-0002-A');
    expect(await screen.findByText('Resource not found.')).toBeInTheDocument();
  });

  it('is translated into Portuguese', async () => {
    window.sessionStorage.setItem(LANGUAGE_STORAGE_KEY, 'pt');
    signInAsStudent();
    server.use(
      http.get(`${API}/academic-requests`, () => HttpResponse.json(academicRequestList)),
    );
    renderApp('/app/academic-requests');
    expect(await screen.findByText('Certidão de matrícula')).toBeInTheDocument();
    expect(screen.getByText('Os meus pedidos académicos')).toBeInTheDocument();
    expect(screen.getByText('Demonstração')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Os meus pedidos' })).toBeInTheDocument();
  });
});
