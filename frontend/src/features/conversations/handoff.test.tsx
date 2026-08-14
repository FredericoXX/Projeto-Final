import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';
import { API } from '../../test/handlers';
import {
  activeConversation,
  archivedConversation,
  closedConversation,
  handoffDestination,
  makeHandoffMessage,
} from '../../test/fixtures';
import { tokenStorage } from '../../api/token';

const CONVERSATION_PATH = `/app/conversations/${activeConversation.id}`;
const BUTTON_NAME = 'Talk to human support';

function authenticate() {
  tokenStorage.set('test-token');
}

function showConversation(conversation: typeof activeConversation) {
  server.use(http.get(`${API}/conversations/:id`, () => HttpResponse.json(conversation)));
}

describe('human handoff action', () => {
  it('offers the action in an active conversation', async () => {
    authenticate();
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByRole('button', { name: BUTTON_NAME })).toBeInTheDocument();
  });

  it.each([
    ['closed', closedConversation],
    ['archived', archivedConversation],
  ])('does not offer the action in a %s conversation', async (_label, conversation) => {
    authenticate();
    showConversation(conversation);
    renderApp(`/app/conversations/${conversation.id}`);

    // A ausência só é significativa depois de a conversa ter carregado.
    expect(await screen.findByText(/does not accept new messages/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: BUTTON_NAME })).not.toBeInTheDocument();
  });

  it('calls the handoff endpoint with an empty body', async () => {
    authenticate();
    const requests: { url: string; method: string; body: string }[] = [];
    server.use(
      http.post(`${API}/conversations/:id/handoff`, async ({ request }) => {
        requests.push({
          url: request.url,
          method: request.method,
          body: await request.text(),
        });
        return HttpResponse.json(
          {
            outcome: 'escalate',
            conversation_id: activeConversation.id,
            destination: { ...handoffDestination },
            assistant_message: makeHandoffMessage(),
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: BUTTON_NAME }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].method).toBe('POST');
    expect(requests[0].url).toBe(
      `${API}/conversations/${activeConversation.id}/handoff`,
    );
    // O cliente não escolhe desfecho, trigger nem destino.
    expect(requests[0].body).toBe('');
  });

  it('shows the persisted assistant message after a successful handoff', async () => {
    authenticate();
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: BUTTON_NAME }));

    expect(
      await screen.findByText(/This request is better handled by human support/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Human support contact provided/)).toBeInTheDocument();
    expect(screen.getByText(`Service: ${handoffDestination.name}`)).toBeInTheDocument();
  });

  it('renders the destination contacts as safe links', async () => {
    authenticate();
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: BUTTON_NAME }));

    const email = await screen.findByRole('link', { name: 'Send email' });
    expect(email).toHaveAttribute('href', `mailto:${handoffDestination.email}`);

    const link = screen.getByRole('link', { name: 'Open support page' });
    expect(link).toHaveAttribute('href', handoffDestination.url);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('never turns a dangerous destination URL into a link', async () => {
    authenticate();
    server.use(
      http.get(`${API}/conversations/:id/messages`, () =>
        HttpResponse.json({
          items: [
            makeHandoffMessage({
              extra_metadata: {
                turn_type: 'human_handoff',
                decision_outcome: 'escalate',
                handoff_mode: 'e1',
                handoff_trigger: 'user_requested',
                message_version: 'human_handoff_e1_v1',
                handoff_destination: {
                  name: 'Academic Services',
                  email: 'not an email',
                  url: 'javascript:alert(1)',
                },
              },
            }),
          ],
          total: 1,
          limit: 100,
          offset: 0,
        }),
      ),
    );
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByText(/Human support contact provided/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open support page' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Send email' })).not.toBeInTheDocument();
  });

  it('keeps the handoff visible from persisted history, without any local state', async () => {
    authenticate();
    server.use(
      http.get(`${API}/conversations/:id/messages`, () =>
        HttpResponse.json({
          items: [makeHandoffMessage()],
          total: 1,
          limit: 100,
          offset: 0,
        }),
      ),
    );
    renderApp(CONVERSATION_PATH);

    // Sem clicar: a mensagem vem do backend, como aconteceria após um reload.
    expect(
      await screen.findByText(/This request is better handled by human support/),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Send email' })).toBeInTheDocument();
  });

  it('disables the button while the request is pending', async () => {
    authenticate();
    let calls = 0;
    let release: () => void = () => {};
    const blocked = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post(`${API}/conversations/:id/handoff`, async () => {
        calls += 1;
        await blocked;
        return HttpResponse.json(
          {
            outcome: 'escalate',
            conversation_id: activeConversation.id,
            destination: { ...handoffDestination },
            assistant_message: makeHandoffMessage(),
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const button = await screen.findByRole('button', { name: BUTTON_NAME });
    await user.click(button);

    const pending = await screen.findByRole('button', { name: 'Handing off…' });
    expect(pending).toBeDisabled();

    // Um segundo clique enquanto está pendente não produz outro pedido: é isto
    // que impede o duplo encaminhamento acidental, já que o backend não tem
    // idempotência.
    await user.click(pending);
    expect(calls).toBe(1);

    release();
    await screen.findByRole('button', { name: BUTTON_NAME });
    expect(calls).toBe(1);
  });

  it('shows a controlled error and keeps the action available when support is unavailable', async () => {
    authenticate();
    server.use(
      http.post(`${API}/conversations/:id/handoff`, () =>
        HttpResponse.json(
          {
            detail: {
              code: 'resource_conflict',
              message: 'Human support is not configured for this institution.',
            },
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: BUTTON_NAME }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/Could not hand off to human support/);
    // O botão não desaparece silenciosamente: continua disponível para retry.
    expect(screen.getByRole('button', { name: BUTTON_NAME })).toBeEnabled();
    // Nenhuma mensagem local foi inserida.
    expect(
      screen.queryByText(/This request is better handled by human support/),
    ).not.toBeInTheDocument();
  });

  it('uses the shared error mapping for failures other than 409', async () => {
    authenticate();
    server.use(http.post(`${API}/conversations/:id/handoff`, () => HttpResponse.error()));
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    await user.click(await screen.findByRole('button', { name: BUTTON_NAME }));

    // A mensagem específica de handoff é reservada ao 409; tudo o resto passa
    // por errorTranslationKey, cujo mapeamento não é alterado por esta branch.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('An unexpected error occurred. Please try again.');
    expect(alert).not.toHaveTextContent(/Could not hand off/);
  });
});
