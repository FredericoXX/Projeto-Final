import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { FullPageLoader } from '../components/feedback/FullPageLoader';

// Sends the user to conversations or login depending on the resolved session,
// showing a loader while the session is still initializing.
export function RootRedirect() {
  const { status } = useAuth();
  if (status === 'initializing') {
    return <FullPageLoader />;
  }
  return <Navigate to={status === 'authenticated' ? '/app/conversations' : '/login'} replace />;
}
