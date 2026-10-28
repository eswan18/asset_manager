import { createBrowserRouter, type RouteObject } from "react-router";

import { AppShell } from "@/components/shell/app-shell";
import { AccountDrawer } from "@/routes/account-drawer";
import { AccountsPage } from "@/routes/accounts";
import { CashFlowCategoriesDrawer } from "@/routes/cash-flow-categories";
import { CashFlowDrawer } from "@/routes/cash-flow-drawer";
import { CashFlowsPage } from "@/routes/cash-flows";
import { DashboardPage } from "@/routes/dashboard";
import { Home } from "@/routes/home";
import { NotFound } from "@/routes/not-found";
import { SettingsPage } from "@/routes/settings";
import { WelcomePage } from "@/routes/welcome";

/** Where the SPA is served (FastAPI: web/spa.py; Vite: `base`). Every path
 * below is relative to it: `/workspaces/1` is `/app/workspaces/1`. At
 * cutover this becomes "/". */
export const BASENAME = "/app";

/**
 * Every page and drawer. URLs keep the Jinja pages' shapes. A drawer is a
 * child route of its page under a pathless layout route, so the page stays
 * mounted (no refetch, no lost scroll) while the drawer opens and closes;
 * the page renders the drawer in its <Outlet />, and the page's own path is
 * an `element: null` child. Page agents: replace the placeholder components,
 * keep the paths.
 */
export const routes: RouteObject[] = [
  { index: true, element: <Home /> },
  {
    element: <AppShell />,
    children: [
      { path: "welcome", element: <WelcomePage /> },
      {
        path: "workspaces/:workspaceId",
        children: [
          { index: true, element: <DashboardPage /> },
          {
            element: <AccountsPage />,
            children: [
              { path: "accounts", element: null },
              { path: "accounts/new", element: <AccountDrawer /> },
              { path: "accounts/:accountId/edit", element: <AccountDrawer /> },
            ],
          },
          {
            element: <CashFlowsPage />,
            children: [
              { path: "cash-flows", element: null },
              { path: "cash-flows/new", element: <CashFlowDrawer /> },
              { path: "cash-flows/:flowId/edit", element: <CashFlowDrawer /> },
              {
                path: "cash-flow-categories",
                element: <CashFlowCategoriesDrawer />,
              },
            ],
          },
          { path: "settings", element: <SettingsPage /> },
          { path: "*", element: <NotFound /> },
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes, { basename: BASENAME });
}
