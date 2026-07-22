import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderApp } from '../test/renderApp';
import { translate } from './index';

describe('translate', () => {
  it('returns the language-specific string', () => {
    expect(translate('pt', 'auth.submit')).toBe('Entrar');
    expect(translate('en', 'auth.submit')).toBe('Sign in');
  });

  it('interpolates parameters', () => {
    expect(translate('en', 'composer.charCount', { count: 3, max: 1000 })).toBe('3/1000');
  });
});

describe('interface language switching', () => {
  it('switches the visible language from the login screen', async () => {
    const user = userEvent.setup();
    renderApp('/login');

    // Usa inglês por omissão no ambiente jsdom (idioma do navegador).
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));

    await user.selectOptions(screen.getByLabelText('Interface language'), 'pt');
    expect(screen.getByRole('button', { name: 'Entrar' })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('pt');
  });
});
