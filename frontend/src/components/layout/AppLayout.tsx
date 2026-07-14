import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../../auth/useAuth';
import { useTranslation } from '../../i18n/useTranslation';
import { LanguageSelector } from './LanguageSelector';

const APP_NAME = import.meta.env.VITE_APP_NAME ?? 'Institutional Assistant';

export function AppLayout() {
  const { user, isAdmin, logout } = useAuth();
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);

  const closeMenu = () => setMenuOpen(false);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        {t('nav.skipToContent')}
      </a>

      {menuOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label={t('common.cancel')}
          onClick={closeMenu}
        />
      )}

      <aside className="sidebar" data-open={menuOpen} aria-label={APP_NAME}>
        <div>
          <div className="sidebar-brand">{APP_NAME}</div>
          <div className="sidebar-tagline">{t('app.tagline')}</div>
        </div>
        <nav className="sidebar-nav" aria-label={t('nav.menu')}>
          <NavLink className="sidebar-link" to="/app/conversations" onClick={closeMenu}>
            {t('nav.conversations')}
          </NavLink>
          {isAdmin && (
            <NavLink className="sidebar-link" to="/admin/documents" onClick={closeMenu}>
              {t('nav.documents')}
            </NavLink>
          )}
        </nav>
      </aside>

      <div className="app-main">
        <header className="app-header">
          <button
            type="button"
            className="btn btn-secondary menu-toggle"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {t('nav.menu')}
          </button>
          <div className="app-header-actions">
            <LanguageSelector />
            {user && (
              <div className="profile">
                <span className="profile-name">{user.full_name}</span>
                <span className="profile-role">{user.role}</span>
              </div>
            )}
            <button type="button" className="btn btn-ghost" onClick={logout}>
              {t('auth.logout')}
            </button>
          </div>
        </header>
        <main id="main-content" className="app-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
