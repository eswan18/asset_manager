import { Link, useLocation, useNavigate } from "react-router";

import { pagePrefetch, usePrefetch } from "@/api/prefetch";
import type { Me } from "@/api/shell";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { initials } from "@/lib/wording";

import {
  AccountsIcon,
  CashFlowsIcon,
  ChevronIcon,
  DashboardIcon,
  GearIcon,
} from "./icons";
import { sameSectionIn, sectionOf, tabOf, type Tab } from "./sections";
import { APP_NAME, type CurrentWorkspace } from "./workspace-context";

/**
 * The top bar (base.html's .shell-header). Desktop: wordmark, the pill nav,
 * then the workspace picker, the settings gear and the account menu. Phones
 * (CSS only): the picker is the title, the gear and avatar sit right, the
 * wordmark hides inside a workspace, and the nav becomes the bottom tab bar.
 * Outside a workspace (welcome) only the wordmark and the account menu show.
 */
export function ShellHeader({
  me,
  workspace,
}: {
  me: Me;
  workspace: CurrentWorkspace | null;
}) {
  const { pathname } = useLocation();
  const section = workspace ? sectionOf(pathname, workspace.base) : "";
  const tab = workspace ? tabOf(section) : null;

  return (
    <header
      className={cn(
        "relative mx-auto flex max-w-[1160px] flex-wrap items-center justify-between gap-3 px-gutter py-5",
        "phone:min-h-[60px] phone:flex-nowrap phone:gap-2 phone:py-2",
      )}
    >
      <Link
        to={workspace ? workspace.base : "/"}
        className={cn(
          "font-display text-[20px] font-bold text-ink no-underline",
          "phone:inline-flex phone:min-h-11 phone:items-center",
          workspace && "phone:hidden",
        )}
      >
        {APP_NAME}
      </Link>
      {workspace && <MainNav workspace={workspace} tab={tab} />}
      <div
        className={cn(
          "flex items-center gap-3",
          "phone:min-w-0 phone:flex-auto phone:justify-end phone:gap-2",
        )}
      >
        {workspace && (
          <>
            <WorkspacePicker me={me} workspace={workspace} section={section} />
            <GearLink workspace={workspace} current={tab === "settings"} />
          </>
        )}
        <AccountMenu me={me} />
      </div>
    </header>
  );
}

/** The settings gear; reaching for it starts loading the settings. */
function GearLink({
  workspace,
  current,
}: {
  workspace: CurrentWorkspace;
  current: boolean;
}) {
  const prefetch = usePrefetch(...pagePrefetch(workspace.id, "settings"));
  return (
    <Link
      to={`${workspace.base}/settings`}
      aria-label="Workspace settings"
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex size-10 items-center justify-center rounded-full bg-surface text-ink shadow-pill",
        "aria-[current=page]:bg-ink aria-[current=page]:text-surface",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-asset",
        "phone:size-11 phone:flex-[0_0_44px]",
      )}
      {...prefetch}
    >
      <GearIcon />
    </Link>
  );
}

const TABS = [
  { tab: "dashboard", path: "", label: "Dashboard", Icon: DashboardIcon },
  { tab: "accounts", path: "/accounts", label: "Accounts", Icon: AccountsIcon },
  {
    tab: "cash_flows",
    path: "/cash-flows",
    label: "Cash flows",
    Icon: CashFlowsIcon,
  },
] as const;

/** The pill nav; on phones, the bottom tab bar (`data-tabbar` sets
 * `--tabbar-h`, so anything fixed to the bottom sits above it). */
function MainNav({
  workspace,
  tab,
}: {
  workspace: CurrentWorkspace;
  tab: Tab;
}) {
  return (
    <nav
      aria-label="Main"
      data-tabbar=""
      className={cn(
        "flex gap-1 rounded-full bg-surface p-1 shadow-pill",
        "phone:fixed phone:inset-x-0 phone:bottom-0 phone:z-30 phone:grid phone:h-tabbar phone:grid-cols-3 phone:gap-0",
        "phone:rounded-none phone:p-0 phone:pb-[env(safe-area-inset-bottom,0px)] phone:shadow-[inset_0_1px_0_var(--rule-strong)]",
      )}
    >
      {TABS.map(({ tab: name, path, label, Icon }) => (
        <NavTab
          key={name}
          workspace={workspace}
          path={path}
          current={tab === name}
        >
          <Icon current={tab === name} />
          {label}
        </NavTab>
      ))}
    </nav>
  );
}

/** A tab; reaching for it starts loading its page's data. */
function NavTab({
  workspace,
  path,
  current,
  children,
}: {
  workspace: CurrentWorkspace;
  /** "", "/accounts" or "/cash-flows". */
  path: string;
  current: boolean;
  children: React.ReactNode;
}) {
  const prefetch = usePrefetch(...pagePrefetch(workspace.id, path.slice(1)));
  return (
    <Link
      to={workspace.base + path}
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex min-h-10 items-center rounded-full px-[18px] whitespace-nowrap text-muted no-underline hover:text-ink",
        "aria-[current=page]:bg-ink aria-[current=page]:font-medium aria-[current=page]:text-surface",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-asset",
        "phone:min-h-14 phone:flex-col phone:justify-center phone:gap-[3px] phone:rounded-none phone:px-1",
        "phone:text-[12px] phone:leading-[1.2] phone:[-webkit-tap-highlight-color:transparent]",
        "phone:aria-[current=page]:bg-transparent phone:aria-[current=page]:font-semibold phone:aria-[current=page]:text-ink",
        "phone:focus-visible:rounded-xl phone:focus-visible:-outline-offset-4",
      )}
      {...prefetch}
    >
      {children}
    </Link>
  );
}

/** Switch workspace, staying in the same section. On phones it is the page
 * title, its "Workspace" label visually hidden. */
function WorkspacePicker({
  me,
  workspace,
  section,
}: {
  me: Me;
  workspace: CurrentWorkspace;
  section: string;
}) {
  const navigate = useNavigate();
  // Reaching for the picker starts loading this section in the others
  // (one read each; most people have a workspace or two).
  const prefetch = usePrefetch(
    ...me.workspaces
      .filter((other) => other.id !== workspace.id)
      .flatMap((other) => pagePrefetch(other.id, section)),
  );
  return (
    <label
      className={cn(
        "relative flex items-center gap-2 text-[13px] text-muted",
        "phone:mr-auto phone:min-w-0 phone:flex-[0_1_auto] phone:text-ink",
      )}
    >
      <span className="phone:sr-only">Workspace</span>
      <select
        {...prefetch}
        value={workspace.id}
        onChange={(event) =>
          navigate(sameSectionIn(Number(event.target.value), section))
        }
        className={cn(
          "min-h-10 rounded-input border-0 bg-surface px-3 text-[15px] text-ink shadow-pill",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-asset",
          "phone:min-h-11 phone:w-auto phone:max-w-full phone:min-w-0 phone:cursor-pointer phone:appearance-none phone:[field-sizing:content]",
          "phone:rounded-none phone:bg-transparent phone:py-0 phone:pr-[26px] phone:pl-0 phone:shadow-none",
          "phone:overflow-hidden phone:font-display phone:text-[17px] phone:font-semibold phone:tracking-[-0.01em] phone:text-ellipsis phone:whitespace-nowrap",
          "phone:focus-visible:rounded-md",
        )}
      >
        {me.workspaces.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
      <ChevronIcon />
    </label>
  );
}

/** The avatar and its menu: who you are, New workspace, Log out. Log out is
 * a full navigation (the server ends the session here and at identity). */
function AccountMenu({ me }: { me: Me }) {
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger
        aria-label={`Account menu for ${me.name || me.email}`}
        className={cn(
          "flex size-10 cursor-pointer items-center justify-center rounded-full bg-surface text-[13px] font-semibold text-ink shadow-pill",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-asset",
          "phone:size-11 phone:flex-[0_0_44px]",
        )}
      >
        {initials(me.name || me.email)}
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>
          {me.name && <strong className="font-semibold">{me.name}</strong>}
          <span className="text-[13px] text-muted">{me.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuItem asChild>
          <Button asChild variant="secondary">
            <Link to="/welcome">New workspace</Link>
          </Button>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Button asChild variant="outline">
            <a href="/logout">Log out</a>
          </Button>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
