import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import {
  Navigate,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router";

import {
  useCashFlowsOverview,
  useCashFlowsPeriod,
  useCashFlowWrites,
  type CashFlowsOverview,
  type FlowRow,
} from "@/api/cash-flows";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
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
import { APP_NAME, useWorkspace } from "@/components/shell/workspace-context";
import {
  flowEyebrow,
  formRates,
  money,
  parseFlowForm,
  unsigned,
  UNITS,
  type FlowForm,
} from "@/lib/cash-flows";
import { cn } from "@/lib/utils";

/**
 * `cash-flows/new` and `cash-flows/:flowId/edit` (cash_flow_form.html): a
 * cash flow's form, over the Cash flows page in its period. `new` takes
 * `?direction=` and `?category_id=` so each card's + Add starts in that
 * card (anything unknown is an uncategorized expense). The header follows
 * the choices ("Edit expense · Food", in the category's color on the page;
 * income is blue), and the rates strip shows the amount a day, a month and
 * a year as it is typed. Saving or deleting goes back to the page with a
 * flash; a refusal shows in the drawer, keeping the input.
 *
 * The drawers only write, so a viewer is sent back to the page (the server
 * answers 403), as is an edit of a flow that isn't there (404).
 */
export function CashFlowDrawer() {
  const workspace = useWorkspace();
  const { flowId } = useParams();
  const { period, pageHref } = useCashFlowsPeriod(workspace.base);
  const overview = useCashFlowsOverview(workspace.id, period);
  const writes = useCashFlowWrites(workspace.id);

  if (!workspace.canEdit) return <Navigate to={pageHref} replace />;
  const view = overview.data;
  if (!view) return null;

  let flow: FlowRow | undefined;
  if (flowId !== undefined) {
    flow = view.cards
      .flatMap((c) => c.flows)
      .find((f) => String(f.id) === flowId);
    if (!flow) {
      // Gone: deleted here (and the drawer is closing), or never there.
      return writes.remove.isIdle ? <Navigate to={pageHref} replace /> : null;
    }
  }
  return (
    <FlowDrawer
      key={flowId ?? "new"}
      view={view}
      flow={flow}
      pageHref={pageHref}
      writes={writes}
    />
  );
}

function initialForm(
  flow: FlowRow | undefined,
  view: CashFlowsOverview,
  params: URLSearchParams,
): FlowForm {
  if (flow) {
    return {
      name: flow.name,
      direction: flow.direction,
      amount: flow.amount,
      every: String(flow.every),
      unit: flow.unit,
      categoryId: flow.category_id === null ? "" : String(flow.category_id),
      isEstimate: flow.is_estimate,
      description: flow.description ?? "",
    };
  }
  const direction = params.get("direction");
  const category = params.get("category_id");
  return {
    name: "",
    direction: direction === "income" ? "income" : "expense",
    amount: "",
    every: "1",
    unit: "month",
    // Only one of this workspace's categories.
    categoryId: view.categories.some((c) => String(c.id) === category)
      ? (category as string)
      : "",
    isEstimate: false,
    description: "",
  };
}

const RATE_CELLS = [
  { key: "perDay", label: "a day", id: "rate-day" },
  { key: "perMonth", label: "a month", id: "rate-month" },
  { key: "perYear", label: "a year", id: "rate-year" },
] as const;

function FlowDrawer({
  view,
  flow,
  pageHref,
  writes,
}: {
  view: CashFlowsOverview;
  flow: FlowRow | undefined;
  pageHref: string;
  writes: ReturnType<typeof useCashFlowWrites>;
}) {
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [form, setForm] = useState(() => initialForm(flow, view, params));
  const [error, setError] = useState<string | null>(null);
  const title = flow ? flow.name : "New cash flow";

  useEffect(() => {
    document.title = `${title} · ${workspace.name} · ${APP_NAME}`;
  }, [title, workspace.name]);

  const set = <K extends keyof FlowForm>(key: K, value: FlowForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const direction = form.direction === "income" ? "income" : "expense";
  const category = view.categories.find(
    (c) => String(c.id) === form.categoryId,
  );
  const color =
    direction === "income"
      ? view.income_color
      : (category?.expense_color ?? view.uncategorized_color);
  const rates = formRates(form.amount, form.every, form.unit);
  const busy =
    writes.create.isPending ||
    writes.update.isPending ||
    writes.remove.isPending;

  async function save(event: FormEvent) {
    event.preventDefault();
    const parsed = parseFlowForm(form);
    if ("error" in parsed) {
      setError(parsed.error);
      return;
    }
    try {
      const saved = flow
        ? await writes.update.mutateAsync({
            id: flow.id,
            fields: parsed.fields,
          })
        : await writes.create.mutateAsync(parsed.fields);
      // The month, whatever the page's period, so it reads the same everywhere.
      flash.success(
        `${flow ? "Saved" : "Added"} ${saved.name}: ${money(unsigned(saved.per_month))} a month.`,
      );
      navigate(pageHref);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function remove() {
    if (!flow) return;
    try {
      await writes.remove.mutateAsync(flow.id);
      flash.success(`Deleted ${flow.name}`);
      navigate(pageHref);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <RouteSheet closeTo={pageHref}>
      <SheetContent style={{ "--section": color } as CSSProperties}>
        <SheetHeader
          eyebrow={
            <span data-slot="eyebrow">
              {flowEyebrow(Boolean(flow), direction, category?.name)}
            </span>
          }
          title={title}
        />
        <SheetForm id="flow-form" onSubmit={save}>
          <SheetBody>
            {error && <SheetError>{error}</SheetError>}

            <fieldset className="grid min-w-0 grid-cols-2 gap-0.5 rounded-full border-0 bg-chip p-[3px]">
              <legend className="sr-only">Direction</legend>
              {(["income", "expense"] as const).map((value) => (
                <label
                  key={value}
                  className={cn(
                    "group relative flex min-h-10 cursor-pointer items-center justify-center gap-2 rounded-full text-muted phone:min-h-11",
                    "has-checked:bg-surface has-checked:font-semibold has-checked:text-ink has-checked:shadow-pill",
                    "has-focus-visible:outline-2 has-focus-visible:outline-offset-1 has-focus-visible:outline-asset",
                  )}
                >
                  <input
                    type="radio"
                    name="direction"
                    value={value}
                    checked={form.direction === value}
                    onChange={() => set("direction", value)}
                    className="absolute size-px opacity-0"
                  />
                  <span
                    aria-hidden="true"
                    className={cn(
                      "hidden size-2 rounded-full group-has-checked:inline-block",
                      value === "income" ? "bg-asset" : "bg-liability",
                    )}
                  />
                  {value === "income" ? "Income" : "Expense"}
                </label>
              ))}
            </fieldset>

            <Field label="Name">
              <Input
                name="name"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                required
                data-autofocus=""
              />
            </Field>

            <div
              data-slot="frequency"
              className={cn(
                "grid grid-cols-[1.3fr_auto_0.7fr_1fr] items-end gap-2.5",
                // The unit and the count keep their width (all of "month"
                // shows); the amount takes what is left.
                "phone:grid-cols-[minmax(0,1fr)_auto_46px_84px] phone:gap-2",
                "phone:[&_input]:px-2.5 phone:[&_select]:pr-1 phone:[&_select]:pl-2.5",
              )}
            >
              <Field label="Amount ($)">
                <Input
                  num
                  name="amount"
                  value={form.amount}
                  onChange={(e) => set("amount", e.target.value)}
                  inputMode="decimal"
                  placeholder="0.00"
                  required
                />
              </Field>
              <span
                aria-hidden="true"
                className="flex min-h-11 items-center text-muted"
              >
                every
              </span>
              <label className="flex flex-col">
                <span className="sr-only">Every how many</span>
                <Input
                  num
                  name="every"
                  value={form.every}
                  onChange={(e) => set("every", e.target.value)}
                  inputMode="numeric"
                  required
                />
              </label>
              <label className="flex flex-col">
                <span className="sr-only">Unit</span>
                <Select
                  name="unit"
                  value={form.unit}
                  onChange={(e) => set("unit", e.target.value)}
                >
                  {UNITS.map((unit) => (
                    <option key={unit} value={unit}>
                      {unit}
                    </option>
                  ))}
                </Select>
              </label>
            </div>

            {/* A day / a month / a year, the month emphasised. On phones
                each column starts from its amount's width, so a year's six
                figures stay on one line. */}
            <div
              data-slot="rates"
              aria-live="polite"
              className="grid grid-cols-3 overflow-hidden rounded-xl bg-chip phone:grid-cols-[repeat(3,auto)]"
            >
              {RATE_CELLS.map((cell) => (
                <div
                  key={cell.id}
                  className="flex min-w-0 flex-col gap-0.5 px-3.5 py-3 [&+&]:border-l-2 [&+&]:border-surface phone:px-2 phone:py-2.5"
                >
                  <span className="text-[12px] text-muted">{cell.label}</span>
                  <strong
                    id={cell.id}
                    className={cn(
                      "font-display font-semibold [overflow-wrap:anywhere]",
                      cell.key === "perMonth"
                        ? "text-[20px] phone:text-[16px]"
                        : "text-[16px] phone:text-[14px]",
                      "phone:tracking-[-0.01em]",
                    )}
                  >
                    {rates ? rates[cell.key] : "—"}
                  </strong>
                </div>
              ))}
            </div>

            <Field label="Category">
              <Select
                name="category_id"
                id="category-select"
                value={form.categoryId}
                onChange={(e) => set("categoryId", e.target.value)}
              >
                <option value="">Uncategorized</option>
                {view.categories.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </Field>

            <label
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-xl bg-estimate-bg px-3.5 py-3 text-estimate-fg phone:min-h-11",
                "has-focus-visible:outline-2 has-focus-visible:outline-offset-1 has-focus-visible:outline-asset",
              )}
            >
              <input
                type="checkbox"
                name="is_estimate"
                checked={form.isEstimate}
                onChange={(e) => set("isEstimate", e.target.checked)}
                className="mt-px size-[18px] flex-none accent-estimate-fg"
              />
              <span className="flex flex-col gap-0.5 text-[13px]">
                <strong className="text-[15px] font-semibold">
                  ≈ This is an estimate
                </strong>
                The amount varies; it's marked ≈ and counted in the estimate
                total.
              </span>
            </label>

            <Field
              label={
                <>
                  Note <span className="font-normal">(optional)</span>
                </>
              }
            >
              <Textarea
                name="description"
                rows={3}
                value={form.description}
                onChange={(e) => set("description", e.target.value)}
              />
            </Field>
          </SheetBody>
          <SheetFooter>
            {flow && (
              <Button
                variant="danger"
                className="mr-auto px-3!"
                onClick={remove}
                disabled={busy}
              >
                Delete
              </Button>
            )}
            <SheetClose asChild>
              <Button variant="outline">Cancel</Button>
            </SheetClose>
            <Button type="submit" variant="primary" disabled={busy}>
              Save
            </Button>
          </SheetFooter>
        </SheetForm>
      </SheetContent>
    </RouteSheet>
  );
}
