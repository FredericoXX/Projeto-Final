import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './useAuth';
import { FullPageLoader } from '../components/feedback/FullPageLoader';
import { AccessDeniedPage } from '../features/common/AccessDeniedPage';

// Admin-only gate. The backend still authorizes every admin request; this only
// avoids offering admin UI to non-admins (defense in depth, not the boundary).
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
