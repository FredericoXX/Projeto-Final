import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './useAuth';
import { FullPageLoader } from '../components/feedback/FullPageLoader';

// Não renderiza conteúdo sensível até a sessão ser resolvida: durante
// `initializing`, apresenta um indicador, nunca o conteúdo protegido.
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'initializing') {
    return <FullPageLoader />;
  }
  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
