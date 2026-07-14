import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';
import { API } from '../../test/handlers';
import { activeConversation, closedConversation, makeMessage } from '../../test/fixtures';
import { tokenStorage } from '../../api/token';

const CONVERSATION_PATH = `/app/conversations/${activeConversation.id}`;

function authenticate() {
  tokenStorage.set('test-token');
}

describe('conversation list and creation', () => {
  it('lists conversations', async () => {
    authenticate();
    renderApp('/app/conversations');
    expect(await screen.findByText('Academic matters')).toBeInTheDocument();
  });

  it('shows an empty state when there are no conversations', async () => {
    authenticate();
    server.use(
      http.get(`${API}/conversations`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
    );
    renderApp('/app/conversations');
    expect(
      await screen.findByText('No conversations yet. Create the first one.'),
    ).toBeInTheDocument();
  });

  it('creates a conversation and opens it', async () => {
    authenticate();
    const user = userEvent.setup();
    renderApp('/app/conversations');

    await user.click(await screen.findByRole('button', { name: 'New conversation' }));
    await user.type(screen.getByLabelText('Title (optional)'), 'My topic');
    await user.click(screen.getByRole('button', { name: 'Create conversation' }));

    // Navigated to the new conversation view (composer visible).
    expect(await screen.findByLabelText('Your question')).toBeInTheDocument();
  });
});

describe('asking a question', () => {
  it('appends the user and assistant messages on an answered turn', async () => {
    authenticate();
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const input = await screen.findByLabelText('Your question');
    await user.type(input, 'When does enrollment open?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByText('When does enrollment open?')).toBeInTheDocument();
    expect(
      await screen.findByText('The enrollment period runs in September.'),
    ).toBeInTheDocument();
    // Text cleared after a successful turn.
    expect(screen.getByLabelText('Your question')).toHaveValue('');
  });

  it('shows the insufficient-evidence note without treating it as an error', async () => {
    authenticate();
    server.use(
      http.post(`${API}/conversations/:id/ask`, async ({ request }) => {
        const body = (await request.json()) as { query: string };
        return HttpResponse.json(
          {
            status: 'insufficient_evidence',
            conversation_id: activeConversation.id,
            user_message: {
              id: 'u1',
              conversation_id: activeConversation.id,
              institution_id: activeConversation.institution_id,
              user_id: 'user',
              role: 'user',
              content: body.query,
              language: 'pt',
              reply_to_message_id: null,
              extra_metadata: null,
              created_at: '2026-02-01T09:10:00Z',
              sources: [],
            },
            assistant_message: {
              id: 'a1',
              conversation_id: activeConversation.id,
              institution_id: activeConversation.institution_id,
              user_id: null,
              role: 'assistant',
              content: 'Not enough information.',
              language: 'pt',
              reply_to_message_id: 'u1',
              extra_metadata: { answer_status: 'insufficient_evidence' },
              created_at: '2026-02-01T09:10:01Z',
              sources: [],
            },
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.type(await screen.findByLabelText('Your question'), 'transport prices?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByText('Not enough information.')).toBeInTheDocument();
    // The note has a leading icon, so match on a substring.
    expect(
      screen.getByText(/Not enough institutional information was found/),
    ).toBeInTheDocument();
    // insufficient_evidence is not an error: no alert is shown.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not add a local message on a 502 and keeps the typed text', async () => {
    authenticate();
    server.use(
      http.post(`${API}/conversations/:id/ask`, () =>
        HttpResponse.json({ detail: { code: 'upstream_error', message: 'x' } }, { status: 502 }),
      ),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const input = await screen.findByLabelText('Your question');
    await user.type(input, 'a question that fails');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Answer generation failed.');
    // No message bubble was inserted (the empty state remains).
    expect(document.querySelectorAll('article.message')).toHaveLength(0);
    // The text is preserved in the composer for retry.
    expect(input).toHaveValue('a question that fails');
  });

  it('does not add a local message on a 503 and keeps the typed text', async () => {
    authenticate();
    server.use(
      http.post(`${API}/conversations/:id/ask`, () =>
        HttpResponse.json(
          { detail: { code: 'service_unavailable', message: 'x' } },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const input = await screen.findByLabelText('Your question');
    await user.type(input, 'a question while unavailable');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The generation service is currently unavailable.',
    );
    expect(document.querySelectorAll('article.message')).toHaveLength(0);
    expect(input).toHaveValue('a question while unavailable');
  });

  it.each([
    {
      status: 409 as const,
      code: 'resource_conflict',
      expected: 'The operation conflicted with the current state.',
    },
    {
      status: 422 as const,
      code: 'validation_error',
      expected: 'Please check the values you entered.',
    },
  ])(
    'keeps the draft and history unchanged after a $status response',
    async ({ status, code, expected }) => {
      authenticate();
      server.use(
        http.post(`${API}/conversations/:id/ask`, () =>
          HttpResponse.json({ detail: { code, message: 'safe' } }, { status }),
        ),
      );
      const user = userEvent.setup();
      renderApp(CONVERSATION_PATH);

      const input = await screen.findByLabelText('Your question');
      await user.type(input, `question returning ${status}`);
      await user.click(screen.getByRole('button', { name: 'Send' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(expected);
      expect(document.querySelectorAll('article.message')).toHaveLength(0);
      expect(input).toHaveValue(`question returning ${status}`);
    },
  );

  it('sends with Enter and inserts a newline with Shift+Enter', async () => {
    authenticate();
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const input = await screen.findByLabelText('Your question');
    await user.type(input, 'first line');
    await user.type(input, '{Shift>}{Enter}{/Shift}');
    expect(input).toHaveValue('first line\n');

    await user.type(input, 'second line{Enter}');
    expect(
      await screen.findByText('The enrollment period runs in September.'),
    ).toBeInTheDocument();
  });

  it('does not submit twice while a request is pending', async () => {
    authenticate();
    let calls = 0;
    server.use(
      http.post(`${API}/conversations/:id/ask`, async ({ request }) => {
        calls += 1;
        await new Promise((resolve) => setTimeout(resolve, 80));
        const body = (await request.json()) as { query: string };
        return HttpResponse.json(
          {
            status: 'answered',
            conversation_id: activeConversation.id,
            user_message: {
              id: `u-${calls}`,
              conversation_id: activeConversation.id,
              institution_id: activeConversation.institution_id,
              user_id: 'user',
              role: 'user',
              content: body.query,
              language: 'pt',
              reply_to_message_id: null,
              extra_metadata: null,
              created_at: '2026-02-01T09:10:00Z',
              sources: [],
            },
            assistant_message: {
              id: `a-${calls}`,
              conversation_id: activeConversation.id,
              institution_id: activeConversation.institution_id,
              user_id: null,
              role: 'assistant',
              content: 'Answer.',
              language: 'pt',
              reply_to_message_id: `u-${calls}`,
              extra_metadata: { answer_status: 'answered' },
              created_at: '2026-02-01T09:10:01Z',
              sources: [],
            },
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const input = await screen.findByLabelText('Your question');
    await user.type(input, 'once{Enter}');
    // While pending the input is disabled, so a second Enter cannot submit.
    await user.type(input, '{Enter}');

    await waitFor(() => expect(screen.getByText('Answer.')).toBeInTheDocument());
    expect(calls).toBe(1);
  });

  it('disables the composer for a closed conversation', async () => {
    authenticate();
    server.use(
      http.get(`${API}/conversations/:id`, () => HttpResponse.json(closedConversation)),
    );
    renderApp(`/app/conversations/${closedConversation.id}`);

    expect(
      await screen.findByText(
        'This conversation is closed and does not accept new messages.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Your question')).not.toBeInTheDocument();
  });
});

describe('message rendering safety', () => {
  it('renders untrusted content as text and never executes it', async () => {
    authenticate();
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const malicious = '<script>alert("xss")</script><img src=x onerror=alert(1)>';
    server.use(
      http.get(`${API}/conversations/:id/messages`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'm1',
              conversation_id: activeConversation.id,
              institution_id: activeConversation.institution_id,
              user_id: null,
              role: 'assistant',
              content: malicious,
              language: 'pt',
              reply_to_message_id: null,
              extra_metadata: { answer_status: 'answered' },
              created_at: '2026-02-01T09:10:01Z',
              sources: [],
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        }),
      ),
    );
    renderApp(CONVERSATION_PATH);

    // The exact string appears as text; no <script>/<img> element was created.
    expect(await screen.findByText(malicious)).toBeInTheDocument();
    const scope = within(document.body);
    expect(scope.queryByRole('img')).not.toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
    expect(alertSpy).not.toHaveBeenCalled();
    alertSpy.mockRestore();
  });

  it('renders system messages with their own role and without sources', async () => {
    authenticate();
    server.use(
      http.get(`${API}/conversations/:id/messages`, () =>
        HttpResponse.json({
          items: [
            makeMessage({
              id: 'system-1',
              role: 'system',
              content: 'Conversation policy notice',
              sources: [],
            }),
          ],
          total: 1,
          limit: 100,
          offset: 0,
        }),
      ),
    );
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByText('Conversation policy notice')).toBeInTheDocument();
    expect(screen.getByText('System')).toBeInTheDocument();
    expect(screen.queryByText('Assistant')).not.toBeInTheDocument();
    expect(screen.queryByText('Sources')).not.toBeInTheDocument();
  });
});

describe('message history pagination', () => {
  it('opens on the latest 100 messages and loads older messages without duplicates', async () => {
    authenticate();
    const total = 150;
    const requestedPages: Array<{ limit: number; offset: number }> = [];
    server.use(
      http.get(`${API}/conversations/:id/messages`, ({ request }) => {
        const url = new URL(request.url);
        const limit = Number(url.searchParams.get('limit'));
        const offset = Number(url.searchParams.get('offset'));
        requestedPages.push({ limit, offset });
        const count = Math.max(0, Math.min(limit, total - offset));
        const items = Array.from({ length: count }, (_, position) => {
          const index = offset + position;
          return makeMessage({
            id: `message-${index}`,
            content: `History message ${index}`,
            created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, index)).toISOString(),
          });
        });
        return HttpResponse.json({ items, total, limit, offset });
      }),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByText('History message 149')).toBeInTheDocument();
    expect(screen.queryByText('History message 0')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Load older messages' }));
    expect(await screen.findByText('History message 0')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll('article.message')).toHaveLength(150));
    expect(requestedPages).toEqual([
      { limit: 100, offset: 0 },
      { limit: 100, offset: 50 },
      { limit: 50, offset: 0 },
    ]);
  });
});
