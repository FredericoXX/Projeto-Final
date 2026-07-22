import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../test/renderApp';
import { server } from '../test/server';
import { API, VALID_EMAIL, VALID_PASSWORD } from '../test/handlers';
import { regularUser } from '../test/fixtures';
import { tokenStorage } from '../api/token';

describe('route guards and session', () => {
  it('redirects an unauthenticated user from a protected route to login', async () => {
    renderApp('/app/conversations');
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('restores the session from a stored token', async () => {
    tokenStorage.set('test-token');
    renderApp('/app/conversations');
    // /auth/me é a fonte de verdade; a lista aparece após restaurar a sessão.
    expect(await screen.findByText('Academic matters')).toBeInTheDocument();
  });

  it('logs out and returns to login, clearing the token', async () => {
    tokenStorage.set('test-token');
    const user = userEvent.setup();
    renderApp('/app/conversations');

    await screen.findByText('Academic matters');
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(tokenStorage.get()).toBeNull();
  });

  it('does not expose cached data after another user logs in', async () => {
    tokenStorage.set('test-token');
    const user = userEvent.setup();
    renderApp('/app/conversations');

    await screen.findByText('Academic matters');
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    await screen.findByRole('button', { name: 'Sign in' });

    server.use(
      http.get(`${API}/auth/me`, () => HttpResponse.json(regularUser)),
      http.get(`${API}/conversations`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'second-user-conversation',
              institution_id: regularUser.institution_id,
              user_id: regularUser.id,
              title: 'Second user conversation',
              language: 'en',
              status: 'active',
              extra_metadata: null,
              created_at: '2026-03-01T10:00:00Z',
              updated_at: '2026-03-01T10:00:00Z',
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        }),
      ),
    );
    await user.type(screen.getByLabelText('Email'), VALID_EMAIL);
    await user.type(screen.getByLabelText('Password'), VALID_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Second user conversation')).toBeInTheDocument();
    expect(screen.queryByText('Academic matters')).not.toBeInTheDocument();
  });

  it('clears the session when a request returns 401', async () => {
    tokenStorage.set('test-token');
    server.use(
      http.get(`${API}/conversations`, () =>
        HttpResponse.json({ detail: { code: 'x', message: 'x' } }, { status: 401 }),
      ),
    );
    renderApp('/app/conversations');
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(tokenStorage.get()).toBeNull();
  });

  it('denies a non-admin access to the admin area', async () => {
    tokenStorage.set('test-token');
    server.use(http.get(`${API}/auth/me`, () => HttpResponse.json(regularUser)));
    renderApp('/admin/documents');
    expect(
      await screen.findByText('You do not have permission to access this area.'),
    ).toBeInTheDocument();
  });

  it('hides the documents navigation from a non-admin', async () => {
    tokenStorage.set('test-token');
    server.use(http.get(`${API}/auth/me`, () => HttpResponse.json(regularUser)));
    renderApp('/app/conversations');
    await screen.findByText('Academic matters');
    expect(screen.queryByRole('link', { name: 'Documents' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Conversations' })).toBeInTheDocument();
  });

  it('shows the documents navigation to an admin', async () => {
    tokenStorage.set('test-token');
    renderApp('/app/conversations');
    await screen.findByText('Academic matters');
    expect(screen.getByRole('link', { name: 'Documents' })).toBeInTheDocument();
  });

  it('renders a 404 page for an unknown route', async () => {
    renderApp('/nowhere');
    await waitFor(() => expect(screen.getByText('404')).toBeInTheDocument());
  });
});
