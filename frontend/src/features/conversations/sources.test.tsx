import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';
import { API } from '../../test/handlers';
import { activeConversation, makeMessage, makeSource } from '../../test/fixtures';
import { tokenStorage } from '../../api/token';

const CONVERSATION_PATH = `/app/conversations/${activeConversation.id}`;

function mockMessagesWithSources(sources: ReturnType<typeof makeSource>[]) {
  server.use(
    http.get(`${API}/conversations/:id/messages`, () =>
      HttpResponse.json({
        items: [makeMessage({ id: 'm-src', sources })],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    ),
  );
}

describe('answer sources', () => {
  it('lists sources ordered by citation index', async () => {
    tokenStorage.set('test-token');
    mockMessagesWithSources([
      makeSource({ id: 's2', citation_index: 1, document_title: 'Second Doc', chunk_id: 'c2' }),
      makeSource({ id: 's1', citation_index: 0, document_title: 'First Doc', chunk_id: 'c1' }),
    ]);
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: /Show sources/ }));
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('First Doc');
    expect(items[1]).toHaveTextContent('Second Doc');
  });

  it('renders an https source as a safe external link', async () => {
    tokenStorage.set('test-token');
    mockMessagesWithSources([makeSource({ source_url: 'https://example.edu/rules' })]);
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: /Show sources/ }));
    const link = screen.getByRole('link', { name: 'Open source' });
    expect(link).toHaveAttribute('href', 'https://example.edu/rules');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('never renders a javascript: URL as a link', async () => {
    tokenStorage.set('test-token');
    mockMessagesWithSources([makeSource({ source_url: 'javascript:alert(1)' })]);
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: /Show sources/ }));
    expect(screen.queryByRole('link', { name: 'Open source' })).not.toBeInTheDocument();
  });

  it('escapes malicious source titles as text', async () => {
    tokenStorage.set('test-token');
    const title = '<img src=x onerror=alert(1)>';
    mockMessagesWithSources([makeSource({ document_title: title })]);
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: /Show sources/ }));
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });
});
