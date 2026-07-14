import { useState, type KeyboardEvent } from 'react';
import { useTranslation } from '../../i18n/useTranslation';

const MAX_QUERY_LENGTH = 1000;

interface ComposerProps {
  disabled: boolean;
  pending: boolean;
  // Resolves true when the turn was persisted (clear the text) or false when it
  // failed (keep the text so the user can retry).
  onSubmit: (query: string, officialOnly: boolean) => Promise<boolean>;
}

export function Composer({ disabled, pending, onSubmit }: ComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState('');
  const [officialOnly, setOfficialOnly] = useState(true);

  async function submit() {
    const trimmed = value.trim();
    // Block empty and concurrent submissions at the UX level (not idempotency).
    if (!trimmed || pending || disabled) {
      return;
    }
    const persisted = await onSubmit(trimmed, officialOnly);
    if (persisted) {
      setValue('');
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <div className="composer">
      <label className="field-label" htmlFor="composer-input">
        {t('composer.label')}
      </label>
      <div className="composer-row">
        <textarea
          id="composer-input"
          className="textarea"
          value={value}
          maxLength={MAX_QUERY_LENGTH}
          rows={2}
          placeholder={t('composer.placeholder')}
          disabled={disabled || pending}
          aria-describedby="composer-hint"
          onKeyDown={handleKeyDown}
          onChange={(event) => setValue(event.target.value)}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={disabled || pending || value.trim().length === 0}
          onClick={() => void submit()}
        >
          {pending ? t('composer.sending') : t('composer.send')}
        </button>
      </div>
      <div className="composer-meta">
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={officialOnly}
            disabled={disabled || pending}
            onChange={(event) => setOfficialOnly(event.target.checked)}
          />
          {t('composer.officialOnly')}
        </label>
        <span id="composer-hint">
          {t('composer.hint')} ·{' '}
          {t('composer.charCount', { count: value.length, max: MAX_QUERY_LENGTH })}
        </span>
      </div>
    </div>
  );
}
