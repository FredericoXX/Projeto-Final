import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './useAuth';
import { FullPageLoader } from '../components/feedback/FullPageLoader';
import { AccessDeniedPage } from '../features/common/AccessDeniedPage';
import type { Permission } from '../types/auth';

// Proteção por permissão da matriz central do backend. O backend continua a
// autorizar cada pedido; isto só evita oferecer uma área a quem não a pode usar.
export function PermissionRoute({
  permission,
  children,
}: {
  permission: Permission;
  children: ReactNode;
}) {
  const { status, can } = useAuth();

  if (status === 'initializing') {
    return <FullPageLoader />;
  }
  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace />;
  }
  if (!can(permission)) {
    return <AccessDeniedPage />;
  }
  return <>{children}</>;
}
