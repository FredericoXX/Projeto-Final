import { Link } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';

export function AccessDeniedPage() {
  const { t } = useTranslation();
  return (
    <div className="content-narrow">
      <div className="card stack" role="alert">
        <h1>{t('common.accessDenied')}</h1>
        <Link className="btn btn-primary" to="/app/conversations">
          {t('common.goHome')}
        </Link>
      </div>
    </div>
  );
}
