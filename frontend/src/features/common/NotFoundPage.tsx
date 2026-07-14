import { Link } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="login-shell">
      <div className="card login-card stack" style={{ textAlign: 'center' }}>
        <h1>404</h1>
        <p className="text-muted">{t('common.notFound')}</p>
        <Link className="btn btn-primary" to="/">
          {t('common.goHome')}
        </Link>
      </div>
    </div>
  );
}
