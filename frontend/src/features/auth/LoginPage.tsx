import { useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth/useAuth';
import { useTranslation } from '../../i18n/useTranslation';
import { ApiError } from '../../api/errors';
import { InlineError } from '../../components/feedback/InlineError';
import { LanguageSelector } from '../../components/layout/LanguageSelector';

const APP_NAME = import.meta.env.VITE_APP_NAME ?? 'Institutional Assistant';

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { login } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const target = (location.state as LocationState | null)?.from ?? '/app/conversations';

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(target, { replace: true });
    } catch (caught) {
      // Falhas de login são intencionalmente genéricas; apenas erros inesperados
      // de transporte apresentam a mensagem de rede.
      if (caught instanceof ApiError && caught.status !== 0) {
        setError(t('auth.invalidCredentials'));
      } else {
        setError(t('error.network'));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-shell">
      <form className="card login-card stack" onSubmit={handleSubmit} noValidate>
        <div className="login-header">
          <div>
            <h1>{APP_NAME}</h1>
            <p className="text-muted text-sm">{t('auth.loginTitle')}</p>
          </div>
          <LanguageSelector />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="login-email">
            {t('auth.email')}
          </label>
          <input
            id="login-email"
            className="input"
            type="email"
            name="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="login-password">
            {t('auth.password')}
          </label>
          <input
            id="login-password"
            className="input"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        {error && <InlineError message={error} />}

        <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
          {submitting ? t('auth.submitting') : t('auth.submit')}
        </button>
      </form>
    </div>
  );
}
