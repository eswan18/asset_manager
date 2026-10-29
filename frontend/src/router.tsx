import { createBrowserRouter, type RouteObject } from "react-router";

import { AppShell } from "@/components/shell/app-shell";
import { Home } from "@/routes/home";
import { NotFound } from "@/routes/not-found";

/**
 * Each page and drawer is its own chunk, so the first load carries only the
 * shell and the page it opens on. The shell, `/`'s redirect and the
 * not-found page are small and stay in the main bundle. Each loader is one
 * `import()`, shared by its route's `lazy` and by `preloadRoutes`, so once
 * preloaded a route's `lazy` resolves from the module cache.
 */
const load = {
  welcome: () => import("@/routes/welcome"),
  dashboard: () => import("@/routes/dashboard"),
  accounts: () => import("@/routes/accounts"),
  accountDrawer: () => import("@/routes/account-drawer"),
  cashFlows: () => import("@/routes/cash-flows"),
  cashFlowDrawer: () => import("@/routes/cash-flow-drawer"),
  cashFlowCategories: () => import("@/routes/cash-flow-categories"),
  settings: () => import("@/routes/settings"),
};

/**
 * Fetch every page and drawer chunk once the browser is idle, after the
 * first render: React Router holds the old page until a lazy route's chunk
 * arrives, so without this the first click on each page or drawer waits for
 * the network. (The dashboard chart stays lazy on its own.)
 */
export function preloadRoutes() {
  const whenIdle =
    window.requestIdleCallback ?? ((run: () => void) => setTimeout(run, 200));
  whenIdle(() => {
    for (const loader of Object.values(load)) {
      // A failed preload is retried by the route's own lazy when it is
      // needed, where the error has somewhere to show.
      loader().catch(() => {});
    }
  });
}

/**
 * Every page and drawer, at the URLs the Jinja pages had (FastAPI serves
 * index.html for them: web/spa.py). A drawer is a child route of its page
 * under a pathless layout route, so the page stays mounted (no refetch, no
 * lost scroll) while the drawer opens and closes; the page renders the
 * drawer in its <Outlet />, and the page's own path is an empty child.
 */
export const routes: RouteObject[] = [
  { index: true, element: <Home /> },
  // A bare /accounts predates workspaces in the URL: Accounts in your
  // oldest workspace, as / goes to its dashboard.
  { path: "accounts", element: <Home section="/accounts" /> },
  {
    element: <AppShell />,
    children: [
      {
        path: "welcome",
        lazy: () => load.welcome().then((m) => ({ Component: m.WelcomePage })),
      },
      {
        path: "workspaces/:workspaceId",
        children: [
          {
            index: true,
            lazy: () =>
              load.dashboard().then((m) => ({ Component: m.DashboardPage })),
          },
          {
            lazy: () =>
              load.accounts().then((m) => ({ Component: m.AccountsPage })),
            children: [
              { path: "accounts", element: null },
              { path: "accounts/new", lazy: accountDrawer },
              { path: "accounts/:accountId/edit", lazy: accountDrawer },
            ],
          },
          {
            lazy: () =>
              load.cashFlows().then((m) => ({ Component: m.CashFlowsPage })),
            children: [
              { path: "cash-flows", element: null },
              { path: "cash-flows/new", lazy: cashFlowDrawer },
              { path: "cash-flows/:flowId/edit", lazy: cashFlowDrawer },
              {
                path: "cash-flow-categories",
                lazy: () =>
                  load.cashFlowCategories().then((m) => ({
                    Component: m.CashFlowCategoriesDrawer,
                  })),
              },
            ],
          },
          {
            path: "settings",
            lazy: () =>
              load.settings().then((m) => ({ Component: m.SettingsPage })),
          },
          { path: "*", element: <NotFound /> },
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];

function accountDrawer() {
  return load.accountDrawer().then((m) => ({ Component: m.AccountDrawer }));
}

function cashFlowDrawer() {
  return load.cashFlowDrawer().then((m) => ({ Component: m.CashFlowDrawer }));
}

/**
 * Every path the router renders a page or drawer for (the not-found
 * catch-alls left out), in router syntax: "/workspaces/:workspaceId/accounts".
 * src/page-routes.json holds the same list for the phone sweep
 * (tests/browser/test_mobile_sweep.py), and router.test.tsx keeps the two
 * equal, so a new route needs a phone screen before it can land.
 */
export function pagePaths(rs: RouteObject[] = routes, base = ""): string[] {
  return rs.flatMap((route) => {
    if (route.index) return [base || "/"];
    if (route.path === "*") return [];
    const full = route.path ? `${base}/${route.path}` : base;
    if (route.children) return pagePaths(route.children, full);
    return [full];
  });
}

export function createAppRouter() {
  return createBrowserRouter(routes);
}
