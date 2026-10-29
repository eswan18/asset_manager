import { useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import {
  useAccount,
  useAccountWrites,
  useAccountsOverview,
  type AccountDetail,
  type AccountType,
  type AccountsOverview,
  type CategoryOption,
  type FormulaIn,
  type InputGroup,
} from "@/api/accounts";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Check, Field, FieldPair, Input, Select } from "@/components/ui/field";
import {
  RouteSheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetError,
  SheetFooter,
  SheetForm,
  SheetHeader,
} from "@/components/ui/sheet";
import { flash } from "@/components/ui/toaster";
import {
  useWorkspace,
  type CurrentWorkspace,
} from "@/components/shell/workspace-context";
import { formatAmount, formatMoney, money, shortDate } from "@/lib/amounts";
import type { Dec } from "@/lib/decimal";
import { formulaPreview, PREVIEW_HINT } from "@/lib/formulas";
import { cn } from "@/lib/utils";

/** `accounts/new` (`?type=asset|liability`) and `accounts/:accountId/edit`
 * (account_form.html): the account form, a drawer over the Accounts page.
 * Name, the type (new accounts only), the category, and "Computed from
 * other accounts" with its rate, basis, inputs and the live computed-value
 * line; an existing account adds its history and Retire or Unretire.
 * Viewers see the edit drawer as editors do, and its writes are refused, as
 * on the Jinja page; the new-account drawer is editor-only. */
export function AccountDrawer() {
  const workspace = useWorkspace();
  const { accountId } = useParams();
  const [search] = useSearchParams();
  const closeTo = `${workspace.base}/accounts`;
  const id = accountId === undefined ? null : Number(accountId);
  const overview = useAccountsOverview(workspace.id);
  const detail = useAccount(workspace.id, id);

  if (id === null && !workspace.canEdit) {
    return (
      <Refusal
        closeTo={closeTo}
        title="New account"
        message="This needs the editor role or higher"
      />
    );
  }
  const failed = overview.error ?? detail.error;
  if (failed) {
    const missing = failed instanceof ApiError && failed.status === 404;
    return (
      <Refusal
        closeTo={closeTo}
        title={missing ? "Account not found" : "Something went wrong"}
        message={
          missing
            ? "There's no such account in this workspace."
            : failed.message
        }
      />
    );
  }
  // Opened once its data is here, so focus lands on the Name field.
  if (!overview.data || (id !== null && !detail.data)) return null;

  const type = search.get("type");
  return (
    <AccountForm
      key={id ?? "new"}
      workspace={workspace}
      closeTo={closeTo}
      categories={overview.data.categories}
      detail={detail.data ?? null}
      newType={type === "liability" ? "liability" : "asset"}
      candidates={
        detail.data
          ? detail.data.eligible_inputs
          : candidatesFrom(overview.data)
      }
    />
  );
}

/** A new account's possible inputs: every active, plain account, under
 * Assets and Liabilities, by name (as the edit drawer's `eligible_inputs`). */
function candidatesFrom(overview: AccountsOverview): InputGroup[] {
  return overview.sections
    .map((section) => ({
      kind: section.kind,
      label: section.title,
      accounts: section.groups
        .flatMap((g) => g.accounts)
        .filter((a) => a.retired_at === null && !a.computed)
        .sort((a, b) => (a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1))
        .map(({ id, name, amount }) => ({ id, name, amount })),
    }))
    .filter((group) => group.accounts.length > 0);
}

function Refusal({
  closeTo,
  title,
  message,
}: {
  closeTo: string;
  title: string;
  message: string;
}) {
  return (
    <RouteSheet closeTo={closeTo}>
      <SheetContent>
        <SheetHeader eyebrow="Accounts" title={title} />
        <SheetBody>
          <SheetError>{message}</SheetError>
        </SheetBody>
        <SheetFooter>
          <SheetClose asChild>
            <Button variant="outline">Close</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </RouteSheet>
  );
}

interface FormState {
  name: string;
  type: AccountType;
  /** A category key; "" is Uncategorized. */
  category: string;
  computed: boolean;
  ratePercent: string;
  costBasis: string;
  inputIds: number[];
}

function initialForm(
  detail: AccountDetail | null,
  newType: AccountType,
): FormState {
  if (detail === null) {
    return {
      name: "",
      type: newType,
      category: "",
      computed: false,
      ratePercent: "",
      costBasis: "",
      inputIds: [],
    };
  }
  const { account } = detail;
  const formula = account.formula;
  return {
    name: account.name,
    type: account.type,
    category: account.category ?? "",
    computed: formula !== null,
    ratePercent: formula?.rate_percent ?? "",
    costBasis: formula ? formatAmount(money(formula.cost_basis)) : "",
    inputIds: formula ? formula.inputs.map((i) => i.id) : [],
  };
}

function AccountForm({
  workspace,
  closeTo,
  categories,
  detail,
  newType,
  candidates,
}: {
  workspace: CurrentWorkspace;
  closeTo: string;
  categories: CategoryOption[];
  detail: AccountDetail | null;
  newType: AccountType;
  candidates: InputGroup[];
}) {
  const navigate = useNavigate();
  const writes = useAccountWrites(workspace.id);
  const [form, setForm] = useState(() => initialForm(detail, newType));
  const [error, setError] = useState<string | null>(null);
  const account = detail?.account ?? null;
  const set = (patch: Partial<FormState>) =>
    setForm((current) => ({ ...current, ...patch }));

  const amounts = new Map<number, Dec>();
  for (const group of candidates) {
    for (const c of group.accounts) {
      if (c.amount !== null) amounts.set(c.id, money(c.amount));
    }
  }
  // In page order, as the form would post them.
  const checkedIds = candidates
    .flatMap((g) => g.accounts)
    .map((c) => c.id)
    .filter((cid) => form.inputIds.includes(cid));
  const preview = formulaPreview(
    form.ratePercent,
    form.costBasis,
    checkedIds,
    amounts,
  );

  const pending =
    writes.create.isPending ||
    writes.update.isPending ||
    writes.retire.isPending ||
    writes.unretire.isPending;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const formula: FormulaIn | null = form.computed
      ? {
          rate_percent: form.ratePercent,
          cost_basis: form.costBasis,
          input_ids: checkedIds,
        }
      : null;
    const category = form.category || null;
    try {
      if (account === null) {
        const added = await writes.create.mutateAsync({
          name: form.name,
          type: form.type,
          category,
          formula,
        });
        flash.success(
          `Added ${added.name} to ${added.type === "asset" ? "assets" : "liabilities"}.`,
        );
      } else {
        const saved = await writes.update.mutateAsync({
          id: account.id,
          body: { name: form.name, category, formula },
        });
        flash.success(`Saved ${saved.name}`);
      }
      navigate(closeTo);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  /** Retire and Unretire act at once and go back to the page with a flash,
   * a refusal included, as the Jinja forms' redirects do. */
  async function lifecycle(action: "retire" | "unretire") {
    if (account === null) return;
    try {
      const done = await writes[action].mutateAsync(account.id);
      flash.success(
        `${action === "retire" ? "Retired" : "Unretired"} ${done.name}`,
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return;
      flash.error(e instanceof Error ? e.message : String(e));
    }
    navigate(closeTo);
  }

  return (
    <RouteSheet closeTo={closeTo}>
      <SheetContent kind={form.type}>
        <SheetHeader
          eyebrow={account ? `Edit ${account.type}` : "New account"}
          title={account ? account.name : `New ${form.type}`}
        />
        <SheetForm onSubmit={submit}>
          <SheetBody>
            {error && <SheetError>{error}</SheetError>}

            <div className="flex flex-col gap-[18px]">
              <Field label="Name">
                <Input
                  name="name"
                  required
                  data-autofocus
                  value={form.name}
                  onChange={(e) => set({ name: e.target.value })}
                />
              </Field>

              {account === null && (
                <Pills legend="Type">
                  {(["asset", "liability"] as const).map((value) => (
                    <Pill
                      key={value}
                      type="radio"
                      name="type"
                      value={value}
                      checked={form.type === value}
                      onChange={() => set({ type: value })}
                    >
                      {value === "asset" ? "Asset" : "Liability"}
                    </Pill>
                  ))}
                </Pills>
              )}

              <Field label="Category">
                <Select
                  name="category"
                  value={form.category}
                  onChange={(e) => set({ category: e.target.value })}
                >
                  <option value="">Uncategorized</option>
                  {categories.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </Field>

              <Check
                label="Computed from other accounts"
                name="computed"
                checked={form.computed}
                onChange={(e) => set({ computed: e.target.checked })}
              />

              {form.computed && (
                <div className="flex flex-col gap-[18px]" data-formula-fields>
                  <FieldPair>
                    <Field label="Rate (%)">
                      <Input
                        num
                        name="rate_percent"
                        inputMode="decimal"
                        placeholder="15"
                        value={form.ratePercent}
                        onChange={(e) => set({ ratePercent: e.target.value })}
                      />
                    </Field>
                    <Field label="Cost basis ($)">
                      <Input
                        num
                        name="cost_basis"
                        inputMode="decimal"
                        placeholder="0.00"
                        value={form.costBasis}
                        onChange={(e) => set({ costBasis: e.target.value })}
                      />
                    </Field>
                  </FieldPair>
                  <Pills legend="Inputs">
                    {candidates.length === 0 && (
                      <p className="text-[14px] text-muted">
                        No plain, active accounts to use as inputs yet.
                      </p>
                    )}
                    {candidates.map((group, i) => [
                      candidates.length > 1 && (
                        <span
                          key={`label-${group.kind}`}
                          className={cn(
                            "basis-full text-[12px] text-muted",
                            i > 0 && "mt-1",
                          )}
                        >
                          {group.label}
                        </span>
                      ),
                      ...group.accounts.map((c) => (
                        <Pill
                          key={c.id}
                          type="checkbox"
                          name="input_ids"
                          value={String(c.id)}
                          checked={form.inputIds.includes(c.id)}
                          onChange={(e) =>
                            set({
                              inputIds: e.target.checked
                                ? [...form.inputIds, c.id]
                                : form.inputIds.filter((x) => x !== c.id),
                            })
                          }
                        >
                          {c.name}
                        </Pill>
                      )),
                    ])}
                  </Pills>
                  <div
                    aria-live="polite"
                    data-formula-preview
                    className={cn(
                      "flex items-baseline justify-between gap-3 rounded-xl bg-chip px-4 py-3.5 text-[14px]",
                      "phone:flex-wrap",
                    )}
                  >
                    <span className="text-muted phone:min-w-0 phone:[overflow-wrap:anywhere]">
                      {preview ? preview.text : PREVIEW_HINT}
                    </span>
                    <strong className="font-display text-[18px] font-semibold whitespace-nowrap">
                      {preview ? preview.value : "—"}
                    </strong>
                  </div>
                </div>
              )}
            </div>

            {detail && (
              <>
                <History history={detail.history} />
                <section
                  aria-label="Retire"
                  className="flex flex-col items-start gap-2.5 border-t border-rule pt-4"
                >
                  {detail.account.retired_at !== null ? (
                    <>
                      <p className="text-[14px] text-muted">
                        Retired {shortDate(detail.account.retired_at)}.
                        Unretiring brings it back with a blank amount.
                      </p>
                      <Button
                        variant="outline"
                        disabled={pending}
                        onClick={() => lifecycle("unretire")}
                      >
                        Unretire
                      </Button>
                    </>
                  ) : detail.retire_blocker ? (
                    <p className="text-[14px] text-muted">
                      {detail.retire_blocker}
                    </p>
                  ) : (
                    <>
                      <p className="text-[14px] text-muted">
                        {detail.retire_warning ??
                          "Retiring hides this account and stops including it in snapshots. History is kept."}
                      </p>
                      <Button
                        variant="danger-outline"
                        disabled={pending}
                        onClick={() => lifecycle("retire")}
                      >
                        {detail.retire_warning ? "Retire anyway" : "Retire"}
                      </Button>
                    </>
                  )}
                </section>
              </>
            )}
          </SheetBody>
          <SheetFooter>
            <SheetClose asChild>
              <Button variant="outline">Cancel</Button>
            </SheetClose>
            <Button type="submit" variant="primary" disabled={pending}>
              Save
            </Button>
          </SheetFooter>
        </SheetForm>
      </SheetContent>
    </RouteSheet>
  );
}

/** Checkable pills under a legend: the type choice and the inputs. */
function Pills({
  legend,
  children,
}: {
  legend: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="flex flex-wrap gap-2 border-0">
      <legend className="pb-2 text-[13px] font-medium text-muted">
        {legend}
      </legend>
      {children}
    </fieldset>
  );
}

function Pill({
  children,
  ...props
}: Omit<React.ComponentProps<"input">, "className"> & {
  children: React.ReactNode;
}) {
  return (
    <label
      className={cn(
        "inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-full border border-rule-strong px-3.5 text-[14px]",
        "has-checked:border-asset has-checked:bg-asset-tint",
        "has-focus-visible:outline-2 has-focus-visible:outline-offset-1 has-focus-visible:outline-asset",
        "phone:max-w-full phone:py-1.5",
      )}
    >
      <input className="size-4 accent-primary" {...props} />
      {children}
    </label>
  );
}

/** The account's snapshots, newest first, collapsed. */
function History({ history }: { history: AccountDetail["history"] }) {
  const count = history.length;
  return (
    <details className="group border-t border-rule pt-2">
      <summary
        className={cn(
          "flex min-h-11 cursor-pointer list-none items-center justify-between font-medium [&::-webkit-details-marker]:hidden",
          "after:mr-1.5 after:size-2 after:rotate-45 after:border-r-[1.5px] after:border-b-[1.5px] after:border-muted after:content-['']",
          "group-open:after:-rotate-135",
        )}
      >
        History (
        {count === 0
          ? "no snapshots"
          : `${count} snapshot${count === 1 ? "" : "s"}`}
        )
      </summary>
      {count === 0 ? (
        <p className="py-2 text-[14px] text-muted">
          No snapshots yet. Save one from the Accounts page.
        </p>
      ) : (
        history.map((row) => (
          <div
            key={row.date}
            className="flex min-h-10 items-center justify-between border-t border-rule text-[14px]"
          >
            <span className="text-muted">{shortDate(row.date)}</span>
            <span>{formatMoney(money(row.amount))}</span>
          </div>
        ))
      )}
    </details>
  );
}
