import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './useAuth';
import { FullPageLoader } from '../components/feedback/FullPageLoader';
import { AccessDeniedPage } from '../features/common/AccessDeniedPage';

// Proteção exclusiva para administradores. O backend continua a autorizar cada
// pedido; isto só evita oferecer a interface administrativa a não administradores.
export function AdminRoute({ children }: { children: ReactNode }) {
  const { status, isAdmin } = useAuth();

  if (status === 'initializing') {
    return <FullPageLoader />;
  }
  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace />;
  }
  if (!isAdmin) {
    return <AccessDeniedPage />;
  }
  return <>{children}</>;
}
