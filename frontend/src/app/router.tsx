import { type RouteObject } from 'react-router-dom';
import { ProtectedRoute } from '../auth/ProtectedRoute';
import { AdminRoute } from '../auth/AdminRoute';
import { AppLayout } from '../components/layout/AppLayout';
import { RootRedirect } from './RootRedirect';
import { LoginPage } from '../features/auth/LoginPage';
import { ConversationsPage } from '../features/conversations/ConversationsPage';
import { ConversationPage } from '../features/conversations/ConversationPage';
import { DocumentsPage } from '../features/documents/DocumentsPage';
import { DocumentDetailPage } from '../features/documents/DocumentDetailPage';
import { NotFoundPage } from '../features/common/NotFoundPage';

export const routes: RouteObject[] = [
  { path: '/', element: <RootRedirect /> },
  { path: '/login', element: <LoginPage /> },
  {
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { path: '/app/conversations', element: <ConversationsPage /> },
      { path: '/app/conversations/:conversationId', element: <ConversationPage /> },
      {
        path: '/admin/documents',
        element: (
          <AdminRoute>
            <DocumentsPage />
          </AdminRoute>
        ),
      },
      {
        path: '/admin/documents/:documentId',
        element: (
          <AdminRoute>
            <DocumentDetailPage />
          </AdminRoute>
        ),
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
];
