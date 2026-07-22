import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { FullPageLoader } from '../components/feedback/FullPageLoader';

// Envia o utilizador para as conversas ou o login conforme a sessão resolvida,
// apresentando um indicador enquanto a sessão ainda está a iniciar.
export function RootRedirect() {
  const { status } = useAuth();
  if (status === 'initializing') {
    return <FullPageLoader />;
  }
  return <Navigate to={status === 'authenticated' ? '/app/conversations' : '/login'} replace />;
}
