import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';
import { API, VALID_EMAIL, VALID_PASSWORD } from '../../test/handlers';
import { tokenStorage } from '../../api/token';

describe('LoginPage', () => {
  it('logs in with valid credentials and reaches conversations', async () => {
    const user = userEvent.setup();
    renderApp('/login');

    await user.type(await screen.findByLabelText('Email'), VALID_EMAIL);
    await user.type(screen.getByLabelText('Password'), VALID_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    // Lands on the conversations list (default fixture title).
    expect(await screen.findByText('Academic matters')).toBeInTheDocument();
    expect(tokenStorage.get()).toBe('test-token');
  });

  it('shows a generic error on invalid credentials and stays on login', async () => {
    const user = userEvent.setup();
    renderApp('/login');

    await user.type(await screen.findByLabelText('Email'), 'wrong@example.edu');
    await user.type(screen.getByLabelText('Password'), 'badpassword');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.');
    expect(tokenStorage.get()).toBeNull();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('does not keep the password in the DOM after a successful login', async () => {
    const user = userEvent.setup();
    renderApp('/login');

    await user.type(await screen.findByLabelText('Email'), VALID_EMAIL);
    await user.type(screen.getByLabelText('Password'), VALID_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await screen.findByText('Academic matters');
    // The login form (and its password input) is unmounted after navigation.
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(VALID_PASSWORD);
  });

  it('surfaces a network error distinctly', async () => {
    server.use(http.post(`${API}/auth/login`, () => HttpResponse.error()));
    const user = userEvent.setup();
    renderApp('/login');

    await user.type(await screen.findByLabelText('Email'), VALID_EMAIL);
    await user.type(screen.getByLabelText('Password'), VALID_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });

  it('clears a token when /auth/me fails after credentials are accepted', async () => {
    server.use(
      http.get(`${API}/auth/me`, () =>
        HttpResponse.json(
          { detail: { code: 'service_unavailable', message: 'temporary failure' } },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp('/login');

    await user.type(await screen.findByLabelText('Email'), VALID_EMAIL);
    await user.type(screen.getByLabelText('Password'), VALID_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(tokenStorage.get()).toBeNull();
  });
});
