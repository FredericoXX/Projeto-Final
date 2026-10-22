import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';
import { API } from '../../test/handlers';
import { activeConversation, makeMessage, makeSource } from '../../test/fixtures';
import { tokenStorage } from '../../api/token';
import type { MessageRead } from '../../types/conversations';
import type { ConversationDecisionResponse, DecisionAction } from '../../types/decision';

// Fixtures técnicas sintéticas do modo experimental: não são casos de avaliação.
const CONVERSATION_PATH = `/app/conversations/${activeConversation.id}`;
const MODE_LABEL = 'Experimental mode (decision policy v1.7)';
const POLICY_VERSION = 'decision_policy_v1.7-experimental.1';

function enablePolicy() {
  server.use(
    http.get(`${API}/decision/status`, () =>
      HttpResponse.json({ enabled: true, policy_version: POLICY_VERSION, catalog_configured: true }),
    ),
  );
}

function decisionMessage(
  action: DecisionAction,
  rule: string,
  extra: Record<string, unknown> = {},
  overrides: Partial<MessageRead> = {},
): MessageRead {
  return makeMessage({
    id: `decision-${action}`,
    content: `Synthetic ${action} message.`,
    reply_to_message_id: 'question-1',
    extra_metadata: {
      turn_type: 'policy_decision',
      decision_outcome: action,
      decision_rule: rule,
      policy_version: POLICY_VERSION,
      message_version: 'decision_messages_v1',
      decision_trigger: 'automatic',
      clarification_options: [],
      gap_items: [],
      temporal_notice: false,
      recommended_destination: null,
      ...extra,
    },
    ...overrides,
  });
}

function showMessages(...messages: MessageRead[]) {
  server.use(
    http.get(`${API}/conversations/:id/messages`, () =>
      HttpResponse.json({ items: messages, total: messages.length, limit: 100, offset: 0 }),
    ),
  );
}

function decideResponse(assistant: MessageRead): ConversationDecisionResponse {
  const metadata = assistant.extra_metadata ?? {};
  return {
    action: metadata['decision_outcome'] as DecisionAction,
    rule: metadata['decision_rule'] as string,
    policy_version: POLICY_VERSION,
    message_version: 'decision_messages_v1',
    conversation_id: activeConversation.id,
    user_message: makeMessage({ id: 'question-1', role: 'user', content: 'Synthetic question' }),
    assistant_message: assistant,
    clarification_options: [],
    destination: null,
    gap_items: [],
    temporal_notice: false,
  };
}

describe('experimental decision policy mode', () => {
  it('is not offered when the backend has it disabled', async () => {
    tokenStorage.set('test-token');
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByRole('textbox')).toBeInTheDocument();
    expect(screen.queryByLabelText(MODE_LABEL)).not.toBeInTheDocument();
  });

  it('keeps B0 as the default and uses the policy endpoint only when selected', async () => {
    tokenStorage.set('test-token');
    enablePolicy();
    const calls: string[] = [];
    server.use(
      http.post(`${API}/conversations/:id/decide`, async ({ request }) => {
        calls.push(`decide:${await request.text()}`);
        return HttpResponse.json(decideResponse(decisionMessage('abstain', 'R01')));
      }),
      http.post(`${API}/conversations/:id/ask`, () => {
        calls.push('ask');
        return HttpResponse.json({ error: 'not used' }, { status: 500 });
      }),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const toggle = await screen.findByLabelText(MODE_LABEL);
    expect(toggle).not.toBeChecked();
    await user.click(toggle);
    await user.type(screen.getByRole('textbox'), 'Synthetic question{Enter}');

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].startsWith('decide:')).toBe(true);
    expect(JSON.parse(calls[0].slice('decide:'.length))).toEqual({
      query: 'Synthetic question',
      official_only: true,
    });
    expect(await screen.findByText('Synthetic abstain message.')).toBeInTheDocument();
    expect(screen.getByText(/Abstention · Rule R01/)).toBeInTheDocument();
  });

  it('renders an answer with its citations and the declared gap', async () => {
    tokenStorage.set('test-token');
    showMessages(
      decisionMessage(
        'answer',
        'R10',
        { gap_items: ['tuition amount'] },
        { sources: [makeSource()] },
      ),
    );
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByText(/Answer · Rule R10/)).toBeInTheDocument();
    expect(
      screen.getByText(/No support in the documents consulted: tuition amount/),
    ).toBeInTheDocument();
    expect(screen.getByText(/grounded/i)).toBeInTheDocument();
  });

  it('shows the recommended destination as a recommendation, never as sent', async () => {
    tokenStorage.set('test-token');
    showMessages(
      decisionMessage(
        'escalate',
        'R02',
        {
          recommended_destination: {
            service_id: 'academic-office',
            name: 'Synthetic Academic Office',
            email: 'office@example.invalid',
            url: null,
          },
          handoff_mode: 'e1',
          handoff_trigger: 'policy_decision',
        },
        { sources: [makeSource()] },
      ),
    );
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByText(/Recommended referral · Rule R02/)).toBeInTheDocument();
    expect(screen.getByText(/the request was not sent to the service/)).toBeInTheDocument();
    expect(screen.getByText(/Synthetic Academic Office/)).toBeInTheDocument();
    // As fontes de um encaminhamento não são apresentadas como resposta fundamentada.
    expect(screen.queryByText(/grounded/i)).not.toBeInTheDocument();
  });

  it('shows the temporal notice of an abstention', async () => {
    tokenStorage.set('test-token');
    showMessages(decisionMessage('abstain', 'R12', { temporal_notice: true }));
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByText(/not in force on the reference date/)).toBeInTheDocument();
  });

  it('continues a clarification by sending only the chosen reading', async () => {
    tokenStorage.set('test-token');
    enablePolicy();
    const clarify = decisionMessage('clarify', 'R06', {
      clarification_options: [
        { reading_id: 'L1', label: 'Enrolment deadline' },
        { reading_id: 'L2', label: 'Tuition deadline' },
      ],
    });
    showMessages(clarify);
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/conversations/:id/decide`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(
          decideResponse(decisionMessage('answer', 'R09', {}, { id: 'decision-answer-2' })),
        );
      }),
    );
    const user = userEvent.setup();
    renderApp(CONVERSATION_PATH);

    const option = await screen.findByRole('button', { name: 'Tuition deadline' });
    await waitFor(() => expect(option).toBeEnabled());
    await user.click(option);

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ clarification: { message_id: clarify.id, reading_id: 'L2' } });
  });

  it('does not offer clarification options when the policy is not available', async () => {
    tokenStorage.set('test-token');
    showMessages(
      decisionMessage('clarify', 'R06', {
        clarification_options: [{ reading_id: 'L1', label: 'Enrolment deadline' }],
      }),
    );
    renderApp(CONVERSATION_PATH);

    expect(await screen.findByRole('button', { name: 'Enrolment deadline' })).toBeDisabled();
  });
});
