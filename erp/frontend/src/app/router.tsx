import { createBrowserRouter, type RouteObject } from 'react-router-dom';

import { AppLayout } from './AppLayout';
import { RouteErrorBoundary } from './ErrorBoundary';
import { RequireAuth } from './guards';
import { ChangePasswordPage } from './pages/ChangePasswordPage';
import { HomePage } from './pages/HomePage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { PATHS } from './paths';
import { featureRoutes } from './registry';

// Component gallery for development; the condition removes route and page from production builds.
const devRoutes: RouteObject[] = import.meta.env.DEV
  ? [{ path: '/_dev/bilesenler', lazy: () => import('./dev/ComponentGallery') }]
  : [];

export const router = createBrowserRouter([
  {
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: PATHS.login, element: <LoginPage /> },
      ...devRoutes,
      {
        element: <RequireAuth />,
        children: [
          { path: PATHS.changePassword, element: <ChangePasswordPage /> },
          {
            element: <AppLayout />,
            children: [
              {
                // Errors of a page stay inside the content area; navigation remains usable.
                errorElement: <RouteErrorBoundary />,
                children: [{ index: true, element: <HomePage /> }, ...featureRoutes, { path: '*', element: <NotFoundPage /> }],
              },
            ],
          },
        ],
      },
    ],
  },
]);
