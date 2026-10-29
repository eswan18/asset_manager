import { useMemo, useRef, useState, type ChangeEvent } from "react";
import { Link, Outlet, useMatch, useParams } from "react-router";

import {
  accountQuery,
  useAccountWrites,
  useAccountsOverview,
  type AccountOut,
  type AccountsOverview,
  type SnapshotSaved,
} from "@/api/accounts";
import { ApiError } from "@/api/client";
import { prefetching, usePrefetch } from "@/api/prefetch";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardGrid,
  CardGroupHead,
  CardHead,
  CardRow,
  CardTitle,
  CardTools,
  CardTotal,
} from "@/components/ui/card";
import { EmptyCard } from "@/components/ui/empty-card";
import { MoneyInput } from "@/components/ui/field";
import {
  Loading,
  Skeleton,
  SkeletonRow,
  SkeletonText,
} from "@/components/ui/skeleton";
import { flash } from "@/components/ui/toaster";
import {
  useDocumentTitle,
  useWorkspace,
  type CurrentWorkspace,
} from "@/components/shell/workspace-context";
import {
  formatAmount,
  formatChange,
  formatDollars,
  formatMoney,
  money,
  readAmount,
  shortDate,
  snapshotLine,
} from "@/lib/amounts";
import { sub, sum, ZERO, type Dec } from "@/lib/decimal";
import {
  amountKey,
  basisKey,
  clearStaged,
  collectSnapshot,
  evaluatePage,
  groupId,
  isDirty,
  readStaged,
  writeStaged,
  type Field,
  type FieldKey,
  type PageAccount,
} from "@/lib/staged-edits";
import { cn } from "@/lib/utils";

const OVERWRITE_WARNING =
  "Today's snapshot already exists. Saving again replaces it.";

/** `/workspaces/:workspaceId/accounts` (accounts.html): every account's
 * latest amount as a field to edit, staged in the page (and in
 * sessionStorage) until Save snapshot. Its drawers (`accounts/new`,
 * `accounts/:accountId/edit`) render in the <Outlet />, over the page,
 * which stays mounted with its staged edits. */
export function AccountsPage() {
  const workspace = useWorkspace();
  const overview = useAccountsOverview(workspace.id);
  useDocumentTitle(useDrawerTitle(overview.data, workspace.name));

  let page = <AccountsSkeleton />;
  if (overview.isError) {
    page = (
      <div
        role="alert"
        className="mb-4 rounded-[14px] bg-danger-tint px-[18px] py-3.5 text-[14px] text-danger"
      >
        An error occurred while loading your data. Please try again later.
      </div>
    );
  } else if (overview.data && !hasAccounts(overview.data)) {
    page = (
      <EmptyCard
        title="No accounts yet"
        text="Accounts are anything with a balance: checking, savings, retirement, your home, loans, cards. Add one, then enter its balance here and save to take a snapshot."
        action={
          workspace.canEdit
            ? {
                label: "+ Add an account",
                to: `${workspace.base}/accounts/new?type=asset`,
              }
            : undefined
        }
        viewerNote="An editor hasn't added any accounts yet."
      />
    );
  } else if (overview.data) {
    // Keyed by workspace: switching workspace starts the page afresh.
    page = (
      <AccountsEditor
        key={workspace.id}
        workspace={workspace}
        overview={overview.data}
      />
    );
  }
  return (
    <>
      {page}
      <Outlet />
    </>
  );
}

/** The first load: the heading and the two cards, a few rows each with an
 * amount field. */
function AccountsSkeleton() {
  const { canEdit } = useWorkspace();
  return (
    <Loading label="Loading accounts">
      <div className="mb-4 px-1 py-2">
        <SkeletonText on="bg" className="w-40 text-[32px]" />
        <SkeletonText on="bg" className="mt-1 w-72 text-[14px]" />
      </div>
      <CardGrid>
        {(["asset", "liability"] as const).map((kind) => (
          <Card key={kind} kind={kind} className="phone:px-4 phone:py-5">
            <CardHead>
              <SkeletonText className="w-28 text-[20px] phone:text-[17px]" />
              <span className="flex items-center gap-3 phone:gap-2">
                {canEdit && (
                  <Skeleton className="h-10 w-[78px] rounded-full phone:size-11" />
                )}
                <SkeletonText className="w-28 text-[20px] phone:text-[17px]" />
              </span>
            </CardHead>
            <SkeletonText className="mt-[18px] mb-1.5 w-32 text-[13px]" />
            <SkeletonRow input name="w-32" />
            <SkeletonRow input name="w-24" />
            <SkeletonRow input name="w-36" />
          </Card>
        ))}
      </CardGrid>
    </Loading>
  );
}

/** The tab's title, as the Jinja page and form set it: the workspace, or
 * "{account} · {workspace}" under an account's drawer ("New account · …"). */
function useDrawerTitle(
  overview: AccountsOverview | undefined,
  workspaceName: string,
): string {
  const { accountId } = useParams();
  const creating = useMatch("/workspaces/:workspaceId/accounts/new");
  if (creating) return `New account · ${workspaceName}`;
  if (accountId === undefined) return workspaceName;
  const account =
    overview && allAccounts(overview).find((a) => String(a.id) === accountId);
  return account ? `${account.name} · ${workspaceName}` : workspaceName;
}

function allAccounts(overview: AccountsOverview): AccountOut[] {
  return overview.sections.flatMap((s) => s.groups.flatMap((g) => g.accounts));
}

function hasAccounts(overview: AccountsOverview): boolean {
  return allAccounts(overview).length > 0;
}

/** The page's fields, in page order, and the active accounts as the
 * formulas see them. */
function pageModel(overview: AccountsOverview) {
  const fields: Field[] = [];
  const accounts: PageAccount[] = [];
  for (const section of overview.sections) {
    for (const group of section.groups) {
      for (const account of group.accounts) {
        if (account.retired_at !== null) continue;
        const formula = account.formula;
        accounts.push({
          id: account.id,
          name: account.name,
          type: account.type,
          group: group.key,
          formula: formula && {
            rate: money(formula.rate),
            costBasis: money(formula.cost_basis),
          },
          inputIds: formula ? formula.inputs.map((i) => i.id) : [],
        });
        fields.push(
          formula
            ? {
                key: basisKey(account.id),
                kind: "basis",
                accountId: account.id,
                label: `Cost basis for ${account.name}`,
                initial: formatAmount(money(formula.cost_basis)),
              }
            : {
                key: amountKey(account.id),
                kind: "amount",
                accountId: account.id,
                label: `Amount for ${account.name}`,
                initial:
                  account.amount === null
                    ? ""
                    : formatAmount(money(account.amount)),
              },
        );
      }
    }
  }
  return { fields, accounts };
}

/** "Saved today's snapshot: 23 accounts, net worth $357,918."
 * (snapshot_saved_text). */
function savedText(saved: SnapshotSaved): string {
  const net = saved.accounts.reduce((total, a) => {
    if (a.amount === null) return total;
    const amount = money(a.amount);
    return a.type === "asset" ? sum([total, amount]) : sub(total, amount);
  }, ZERO);
  const count = saved.count === 1 ? "1 account" : `${saved.count} accounts`;
  return `Saved today's snapshot: ${count}, net worth ${formatDollars(net)}.`;
}

function AccountsEditor({
  workspace,
  overview,
}: {
  workspace: CurrentWorkspace;
  overview: AccountsOverview;
}) {
  const writes = useAccountWrites(workspace.id);
  const { fields, accounts } = useMemo(() => pageModel(overview), [overview]);
  const byKey = useMemo(() => new Map(fields.map((f) => [f.key, f])), [fields]);

  // What's been typed, by field; a field not here shows what it loaded with.
  // A viewer can't save, so has nothing staged to restore.
  const [edits, setEdits] = useState<Record<string, string>>(() =>
    workspace.canEdit ? readStaged() : {},
  );
  const [showRetired, setShowRetired] = useState(false);
  const [saveAttempted, setSaveAttempted] = useState(false);
  // A snapshot already exists for today: the first Save warns, the second
  // overwrites.
  const [overwriteArmed, setOverwriteArmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const inputs = useRef(new Map<FieldKey, HTMLInputElement>());
  const errorBox = useRef<HTMLDivElement>(null);

  const valueOf = (key: FieldKey) =>
    edits[key] ?? byKey.get(key)?.initial ?? "";
  const initialOf = (key: FieldKey) => byKey.get(key)?.initial ?? "";
  const live = evaluatePage(accounts, valueOf);
  const baseline = useMemo(
    () => evaluatePage(accounts, initialOf),
    // initialOf reads byKey, which follows accounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [accounts],
  );

  const dirty = new Set(
    fields.filter((f) => isDirty(f, valueOf(f.key))).map((f) => f.key),
  );
  const editedIds = new Set([...dirty].map((key) => byKey.get(key)!.accountId));
  // A computed row moves when its basis or one of its inputs moves.
  const edited = (account: PageAccount) =>
    editedIds.has(account.id) ||
    account.inputIds.some((id) => editedIds.has(id));
  const byId = new Map(accounts.map((a) => [a.id, a]));

  function change(key: FieldKey, value: string) {
    const next = { ...edits, [key]: value };
    setEdits(next);
    writeStaged(fields, (k) => next[k] ?? initialOf(k));
  }

  /** Leaving a field tidies a number into "1,500.00". */
  function tidy(key: FieldKey) {
    const reading = readAmount(valueOf(key));
    if (reading.kind !== "number") return;
    const text = formatAmount(reading.value);
    if (text !== valueOf(key)) change(key, text);
  }

  function showError(text: string) {
    setError(text);
    if (text) {
      requestAnimationFrame(() =>
        errorBox.current?.scrollIntoView?.({ block: "nearest" }),
      );
    }
  }

  async function save() {
    showError("");
    const { body, problem } = collectSnapshot(fields, valueOf);
    if (problem) {
      setSaveAttempted(true);
      showError(problem.message);
      inputs.current.get(problem.key)?.focus();
      return;
    }
    if (overview.snapshot_is_today && !overwriteArmed) {
      setOverwriteArmed(true);
      return;
    }
    setSaving(true);
    try {
      // Resolves once the page has the saved figures.
      const saved = await writes.save.mutateAsync(body);
      clearStaged();
      setEdits({});
      setSaveAttempted(false);
      setOverwriteArmed(false);
      flash.success(savedText(saved));
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) return;
        showError(
          e.message === `Request failed (${e.status})`
            ? `Save failed (${e.status})`
            : e.message,
        );
      } else {
        showError(`Save failed: ${e instanceof Error ? e.message : e}`);
      }
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    clearStaged();
    setEdits({});
    setSaveAttempted(false);
    setOverwriteArmed(false);
    showError("");
  }

  const dirtyCount = dirty.size;
  let status: string;
  if (saving) status = "Saving…";
  else if (overwriteArmed) status = OVERWRITE_WARNING;
  else if (dirtyCount === 0) status = "No unsaved changes";
  else status = `${dirtyCount} unsaved change${dirtyCount === 1 ? "" : "s"}`;
  const clean = dirtyCount === 0 && !overwriteArmed;

  const fieldProps = (key: FieldKey) => {
    const value = valueOf(key);
    const reading = readAmount(value);
    return {
      value,
      disabled: saving,
      readOnly: !workspace.canEdit,
      edited: dirty.has(key),
      invalid:
        reading.kind === "invalid" ||
        (saveAttempted && reading.kind === "blank" && key.startsWith("amount")),
      onChange: (e: ChangeEvent<HTMLInputElement>) =>
        change(key, e.target.value),
      onBlur: () => tidy(key),
      ref: (el: HTMLInputElement | null) => {
        if (el) inputs.current.set(key, el);
        else inputs.current.delete(key);
      },
    };
  };

  return (
    <>
      <div className="fade-in mb-4 flex flex-wrap items-end justify-between gap-3 px-1 py-2">
        <div>
          <h1 className="font-display text-[32px] font-semibold tracking-[-0.02em]">
            Accounts
          </h1>
          <span className="mt-1 block text-[14px] text-muted">
            {snapshotLine(overview.as_of, overview.last_saved)}
          </span>
        </div>
        {overview.retired_count > 0 && (
          <label className="flex min-h-11 cursor-pointer items-center gap-2 text-[14px] text-muted select-none">
            <input
              type="checkbox"
              className="size-[18px] accent-primary"
              checked={showRetired}
              disabled={saving}
              onChange={(e) => setShowRetired(e.target.checked)}
            />
            Show retired ({overview.retired_count})
          </label>
        )}
      </div>

      {error && (
        <div
          ref={errorBox}
          role="alert"
          className="mb-4 rounded-[14px] bg-danger-tint px-[18px] py-3.5 text-[14px] text-danger"
        >
          {error}
        </div>
      )}

      <CardGrid
        // Dimmed (and still) while the save runs and the figures refetch.
        aria-busy={saving || undefined}
        className={cn("updating fade-in", saving && "pointer-events-none")}
        style={{ animationDelay: "0.05s" }}
      >
        {overview.sections.map((section) => (
          <Card
            key={section.kind}
            kind={section.kind}
            data-section={section.kind}
            className="phone:px-4 phone:py-5"
          >
            <CardHead className="flex-wrap phone:flex-nowrap phone:gap-2">
              <CardTitle className="phone:min-w-0 phone:truncate phone:text-[17px]">
                {section.title}
              </CardTitle>
              <CardTools className="phone:shrink-0 phone:gap-2">
                {workspace.canEdit && (
                  <Button
                    asChild
                    variant="secondary"
                    className={cn(
                      "whitespace-nowrap",
                      // A round "+" on phones, so the head stays one line at
                      // 320px; its name is still "+ Add".
                      "phone:w-11 phone:min-h-11 phone:p-0 phone:text-[0px]",
                      "phone:before:text-[22px] phone:before:leading-none phone:before:font-normal phone:before:[content:'+'_/_'']",
                    )}
                  >
                    <Link
                      to={`${workspace.base}/accounts/new?type=${section.kind}`}
                    >
                      + Add
                    </Link>
                  </Button>
                )}
                <CardTotal className="phone:text-[17px]">
                  {formatMoney(live.totals[section.kind])}
                </CardTotal>
              </CardTools>
            </CardHead>
            {section.groups
              .filter((group) => showRetired || !group.retired)
              .map((group) => (
                <div key={group.key}>
                  <CardGroupHead
                    label={group.label}
                    total={formatMoney(
                      live.subtotals.get(groupId(section.kind, group.key)) ??
                        ZERO,
                    )}
                  />
                  {group.accounts
                    .filter((a) => showRetired || a.retired_at === null)
                    .map((account) => {
                      const model = byId.get(account.id);
                      return (
                        <AccountRow
                          key={account.id}
                          workspaceId={workspace.id}
                          base={workspace.base}
                          account={account}
                          edited={model ? edited(model) : false}
                          computedAmount={live.amounts.get(account.id) ?? null}
                          fieldProps={fieldProps}
                        />
                      );
                    })}
                </div>
              ))}
          </Card>
        ))}
      </CardGrid>

      {workspace.canEdit && (
        <SaveBar
          status={status}
          clean={clean}
          netWorth={formatMoney(live.net)}
          change={
            dirtyCount > 0 ? formatChange(sub(live.net, baseline.net)) : null
          }
          saving={saving}
          saveLabel={
            saving
              ? "Saving…"
              : overwriteArmed
                ? "Overwrite today's snapshot"
                : "Save snapshot"
          }
          onSave={save}
          onDiscard={discard}
        />
      )}
    </>
  );
}

type FieldProps = (key: FieldKey) => {
  value: string;
  disabled: boolean;
  readOnly: boolean;
  edited: boolean;
  invalid: boolean;
  onChange: (e: ChangeEvent<HTMLInputElement>) => void;
  onBlur: () => void;
  ref: (el: HTMLInputElement | null) => void;
};

/** A value that isn't a number reads as an error, over the edited look. */
const INVALID = "border-[1.5px] border-danger text-danger";

/** A viewer's amounts: still labelled fields, but read as plain figures. */
const READ_ONLY = "border-transparent bg-transparent";

function AccountRow({
  workspaceId,
  base,
  account,
  edited,
  computedAmount,
  fieldProps,
}: {
  workspaceId: number;
  base: string;
  account: AccountOut;
  edited: boolean;
  computedAmount: Dec | null;
  fieldProps: FieldProps;
}) {
  // Reaching for the name starts loading its drawer's detail.
  const prefetch = usePrefetch(
    prefetching(accountQuery(workspaceId, account.id)),
  );
  const retired = account.retired_at !== null;
  const computed = !retired && account.formula !== null;
  const was =
    account.amount === null
      ? "nothing yet"
      : formatMoney(money(account.amount));

  let value;
  if (retired) {
    value = (
      <span className="flex-none pr-[13px] text-[12px] text-muted">
        Retired {shortDate(account.retired_at!)}
      </span>
    );
  } else if (computed) {
    value = (
      <span
        className={cn(
          "flex flex-[0_0_140px] flex-col items-end pr-[13px]",
          "phone:[grid-area:1/2/3/3]",
        )}
      >
        <span
          data-computed-amount
          data-edited={edited || undefined}
          className={cn(edited && "font-semibold text-asset")}
        >
          {computedAmount === null ? "—" : formatMoney(computedAmount)}
        </span>
        <span className="text-[12px] text-muted">computed</span>
      </span>
    );
  } else {
    const { invalid, ...props } = fieldProps(amountKey(account.id));
    value = (
      <MoneyInput
        aria-label={`Amount for ${account.name}`}
        aria-invalid={invalid || undefined}
        placeholder="0.00"
        className={cn(
          "flex-[0_0_140px] tabular-nums phone:w-[124px] phone:flex-[0_0_124px]",
          invalid && INVALID,
          props.readOnly && READ_ONLY,
        )}
        {...props}
      />
    );
  }

  return (
    <CardRow
      data-account-id={account.id}
      className={cn(
        computed &&
          "phone:grid phone:grid-cols-[minmax(0,1fr)_auto] phone:items-center phone:gap-x-3 phone:pb-3",
      )}
    >
      <span
        className={cn(
          "flex min-w-0 flex-col gap-1 phone:flex-auto",
          computed && "phone:contents",
        )}
      >
        <Link
          to={`${base}/accounts/${account.id}/edit`}
          {...prefetch}
          className={cn(
            "text-ink no-underline [overflow-wrap:anywhere]",
            "hover:underline hover:decoration-rule-strong hover:underline-offset-3",
            "phone:flex phone:min-h-11 phone:min-w-11 phone:items-center",
            computed && "phone:[grid-area:1/1]",
            retired && "text-muted line-through",
          )}
        >
          {account.name}
        </Link>
        {!retired && edited && (
          <span
            data-was
            className={cn(
              "text-[12px] text-muted",
              computed && "phone:[grid-area:2/1]",
            )}
          >
            was {was}
          </span>
        )}
        {computed && <BasisLine account={account} fieldProps={fieldProps} />}
      </span>
      {value}
    </CardRow>
  );
}

/** A computed row's formula and its cost basis field. */
function BasisLine({
  account,
  fieldProps,
}: {
  account: AccountOut;
  fieldProps: FieldProps;
}) {
  const { edited, invalid, ...props } = fieldProps(basisKey(account.id));
  return (
    <span
      className={cn(
        "flex flex-wrap items-center gap-1.5 text-[12px] text-muted",
        "phone:[grid-area:3/1/4/3] phone:justify-between phone:gap-x-3 phone:gap-y-1",
      )}
    >
      {account.formula!.text}
      <label className="flex items-center gap-1 phone:ml-auto phone:gap-1.5">
        basis $
        <input
          inputMode="decimal"
          aria-label={`Cost basis for ${account.name}`}
          aria-invalid={invalid || undefined}
          data-edited={edited || undefined}
          className={cn(
            "min-h-7 w-[92px] rounded-lg border border-rule-strong bg-input px-2 text-right text-[12px] text-ink",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset",
            "phone:min-h-11 phone:w-[132px] phone:px-3 phone:text-[16px]",
            edited && "border-[1.5px] border-asset bg-asset-tint",
            invalid && INVALID,
            props.readOnly && READ_ONLY,
          )}
          {...props}
        />
      </label>
    </span>
  );
}

/** The sticky save bar: the count, the live net worth and its change, then
 * Discard and Save. On phones it sticks above the tab bar, and at the page's
 * end rests under the last card rather than covering it. */
function SaveBar({
  status,
  clean,
  netWorth,
  change,
  saving,
  saveLabel,
  onSave,
  onDiscard,
}: {
  status: string;
  clean: boolean;
  netWorth: string;
  change: string | null;
  saving: boolean;
  saveLabel: string;
  onSave: () => void;
  onDiscard: () => void;
}) {
  return (
    <div
      data-save-bar-wrap
      className={cn(
        "sticky bottom-0 z-[5] mt-4 pb-5",
        "phone:pointer-events-none phone:bottom-[var(--tabbar-h)]",
        "phone:pb-[max(8px,calc(env(safe-area-inset-bottom,0px)+8px-var(--tabbar-h)))]",
      )}
    >
      <div
        role="region"
        aria-label="Save snapshot"
        className={cn(
          "flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-bar-border bg-bar-bg py-3 pr-3 pl-6 text-bar-fg shadow-menu",
          "phone:pointer-events-auto phone:flex-col phone:flex-nowrap phone:items-stretch phone:gap-2.5 phone:p-3",
        )}
      >
        <span
          aria-live="polite"
          className={cn(
            "flex flex-wrap items-baseline gap-x-5 gap-y-2",
            "phone:flex-nowrap phone:items-start phone:justify-between phone:gap-3 phone:px-1 phone:text-[14px]",
          )}
        >
          <strong
            data-status
            className={cn(
              "font-semibold phone:min-w-0",
              clean && "font-normal text-bar-muted",
            )}
          >
            {status}
          </strong>
          <span className="text-bar-muted phone:shrink-0 phone:text-right">
            <span className="[@media(max-width:360px)]:sr-only">
              Net worth{" "}
            </span>
            <span data-net-worth className="text-bar-fg">
              {netWorth}
            </span>
            {change !== null && (
              <span data-net-change className="phone:block phone:text-[13px]">
                {` (${change})`}
              </span>
            )}
          </span>
        </span>
        <span className="flex gap-2">
          <Button
            variant="outline"
            disabled={saving}
            onClick={onDiscard}
            className="min-h-11 border-bar-border text-bar-fg phone:flex-[1_1_0] phone:px-3"
          >
            Discard
          </Button>
          <Button
            variant="primary"
            busy={saving}
            onClick={onSave}
            className="min-h-11 phone:flex-[1_1_0] phone:px-3"
          >
            {saveLabel}
          </Button>
        </span>
      </div>
    </div>
  );
}
