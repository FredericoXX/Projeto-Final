import { type RouteObject } from 'react-router-dom';
import { ProtectedRoute } from '../auth/ProtectedRoute';
import { PermissionRoute } from '../auth/PermissionRoute';
import { AppLayout } from '../components/layout/AppLayout';
import { RootRedirect } from './RootRedirect';
import { LoginPage } from '../features/auth/LoginPage';
import { ConversationsPage } from '../features/conversations/ConversationsPage';
import { ConversationPage } from '../features/conversations/ConversationPage';
import { DocumentsPage } from '../features/documents/DocumentsPage';
import { DocumentDetailPage } from '../features/documents/DocumentDetailPage';
import { AcademicRequestsPage } from '../features/academicRequests/AcademicRequestsPage';
import { AcademicRequestDetailPage } from '../features/academicRequests/AcademicRequestDetailPage';
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
        path: '/app/academic-requests',
        element: (
          <PermissionRoute permission="academic_requests.read_own">
            <AcademicRequestsPage />
          </PermissionRoute>
        ),
      },
      {
        path: '/app/academic-requests/:requestId',
        element: (
          <PermissionRoute permission="academic_requests.read_own">
            <AcademicRequestDetailPage />
          </PermissionRoute>
        ),
      },
      // O caminho /admin/documents é histórico: a área pertence agora ao gestor
      // documental (knowledge_manager), não ao admin institucional.
      {
        path: '/admin/documents',
        element: (
          <PermissionRoute permission="documents.manage">
            <DocumentsPage />
          </PermissionRoute>
        ),
      },
      {
        path: '/admin/documents/:documentId',
        element: (
          <PermissionRoute permission="documents.manage">
            <DocumentDetailPage />
          </PermissionRoute>
        ),
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
];
