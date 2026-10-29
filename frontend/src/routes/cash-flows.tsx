import { useEffect, type CSSProperties, type ReactNode } from "react";
import { Link, Outlet, useMatch, useSearchParams } from "react-router";

import {
  useCashFlowsOverview,
  useCashFlowsPeriod,
  type BarSlice,
  type CashFlowsOverview,
  type FlowCard,
} from "@/api/cash-flows";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyCard } from "@/components/ui/empty-card";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  Loading,
  Skeleton,
  SkeletonRow,
  SkeletonText,
} from "@/components/ui/skeleton";
import { EstimateTag } from "@/components/ui/tag";
import { APP_NAME, useWorkspace } from "@/components/shell/workspace-context";
import { money, PERIODS, type Period } from "@/lib/cash-flows";
import { cn } from "@/lib/utils";

/** "{title} · {workspace} · Sensibility" while the page shows, and not
 * while a drawer is over it: effects run child first, so a page that set
 * its title on every render would overwrite its drawer's. */
function usePageTitle(title: string, showing: boolean) {
  useEffect(() => {
    if (showing) document.title = `${title} · ${APP_NAME}`;
  }, [title, showing]);
}

const PERIOD_OPTIONS = PERIODS.map((value) => ({
  value,
  label: value[0].toUpperCase() + value.slice(1),
}));

/**
 * `/workspaces/:workspaceId/cash-flows?per=day|month|year` (cash_flows.html):
 * the headline (left over or short each period), "Where income goes" (the
 * bar, its key, and the marker when expenses exceed income), then a card
 * for income, each expense category and Uncategorized. Editors get the
 * controls: rows open their drawer, each card adds into itself. The
 * drawers (`cash-flows/new`, `cash-flows/:flowId/edit`,
 * `cash-flow-categories`) render in the <Outlet /> and keep `?per=`.
 */
export function CashFlowsPage() {
  const workspace = useWorkspace();
  const { period } = useCashFlowsPeriod(workspace.base);
  const [, setParams] = useSearchParams();
  const onPage = useMatch("/workspaces/:workspaceId/cash-flows") !== null;
  usePageTitle(`Cash flows · ${workspace.name}`, onPage);
  const overview = useCashFlowsOverview(workspace.id, period);

  let content = <FlowsSkeleton />;
  if (overview.isError) {
    content = (
      <div
        role="alert"
        className="rounded-[14px] bg-danger-tint px-[18px] py-3.5 text-[14px] text-danger"
      >
        An error occurred while loading your data. Please try again later.
      </div>
    );
  } else if (overview.data) {
    content = (
      <Flows
        view={overview.data}
        period={period}
        updating={overview.isPlaceholderData}
        onPeriod={(per) => setParams({ per })}
      />
    );
  }

  return (
    <>
      {content}
      <Outlet />
    </>
  );
}

/** The first load: the top card (headline, the toggle and buttons, the
 * bar and its key) and a few flow cards. */
function FlowsSkeleton() {
  return (
    <Loading label="Loading cash flows" className="flex flex-col gap-4">
      <Card className="gap-7 p-8 phone:gap-6 phone:px-5 phone:py-6">
        <div className="flex flex-wrap items-end justify-between gap-4 phone:gap-5">
          <div className="flex min-w-0 flex-col gap-1.5">
            <SkeletonText className="w-36 text-[14px]" />
            <Skeleton className="h-16 w-72 max-w-full rounded-xl phone:h-12 phone:w-60" />
            <SkeletonText className="w-60" />
          </div>
          <div className="flex flex-wrap items-center gap-3 phone:w-full">
            <Skeleton className="h-[42px] w-[210px] rounded-full phone:h-[50px] phone:w-full" />
            <Skeleton className="h-12 w-44 rounded-full phone:hidden" />
          </div>
        </div>
        <div className="flex flex-col gap-2.5">
          <SkeletonText className="w-36 text-[14px]" />
          <Skeleton className="h-10 rounded-[10px]" />
          <SkeletonText className="w-full max-w-[520px] text-[13px]" />
        </div>
      </Card>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] items-start gap-4">
        {["w-20", "w-24", "w-28"].map((title) => (
          <Card key={title} className="p-6 phone:p-5">
            <span className="flex items-center justify-between gap-3 pb-2.5">
              <SkeletonText className={cn("text-[18px]", title)} />
              <SkeletonText className="w-24 text-[18px]" />
            </span>
            <span className="border-b border-rule-strong pb-2">
              <SkeletonText className="w-24 text-[13px]" />
            </span>
            <SkeletonRow name="w-32" />
            <SkeletonRow name="w-24" />
          </Card>
        ))}
      </div>
    </Loading>
  );
}

function Flows({
  view,
  period,
  updating,
  onPeriod,
}: {
  view: CashFlowsOverview;
  period: Period;
  /** `view` is the last period's, until this one's arrives. */
  updating: boolean;
  onPeriod: (period: Period) => void;
}) {
  const workspace = useWorkspace();
  const { base, canEdit } = workspace;
  // The figures being replaced, dimmed; the toggle and buttons stay live.
  const figures = { "aria-busy": updating || undefined, className: "updating" };

  if (view.empty) {
    return (
      <div className="fade-in flex flex-col gap-4">
        <EmptyCard
          title="No cash flows yet"
          text="Cash flows are what comes in and goes out on a schedule. Pay, rent, groceries, subscriptions: add your income first, then your expenses, and this page shows where the money goes each month."
          action={
            canEdit
              ? {
                  label: "+ Add income",
                  to: `${base}/cash-flows/new?direction=income&per=${period}`,
                }
              : undefined
          }
          viewerNote="An editor hasn't added any cash flows yet."
        />
      </div>
    );
  }

  return (
    <div className="fade-in flex flex-col gap-4">
      <Card
        data-slot="flows-top"
        className="gap-7 p-8 phone:gap-6 phone:px-5 phone:py-6"
      >
        <div className="flex flex-wrap items-end justify-between gap-4 phone:gap-5">
          <div {...figures} className={cn(figures.className, "min-w-0")}>
            <Headline view={view} />
          </div>
          <div
            data-slot="flows-actions"
            className="flex flex-wrap items-center gap-3 phone:w-full phone:gap-2.5"
          >
            <SegmentedControl
              label="Show amounts per"
              options={PERIOD_OPTIONS}
              value={period}
              onValueChange={onPeriod}
              className="phone:w-full phone:[&>*]:flex-1"
            />
            {canEdit && (
              <div
                data-slot="flows-buttons"
                className="contents phone:flex phone:w-full phone:flex-wrap phone:gap-2.5"
              >
                <Button asChild variant="outline" className={ACTION_BUTTON}>
                  <Link to={`${base}/cash-flow-categories?per=${period}`}>
                    Manage categories
                  </Link>
                </Button>
                <Button asChild variant="primary" className={ACTION_BUTTON}>
                  <Link to={`${base}/cash-flows/new?per=${period}`}>
                    + Add cash flow
                  </Link>
                </Button>
              </div>
            )}
          </div>
        </div>
        <div {...figures}>
          <WhereIncomeGoes view={view} />
        </div>
      </Card>

      <div
        {...figures}
        className={cn(
          figures.className,
          "grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] items-start gap-4",
        )}
      >
        {view.cards.map((card) => (
          <FlowCardView
            key={`${card.direction}-${card.category_id}`}
            card={card}
            period={period}
          />
        ))}
        {canEdit && (
          <Link
            to={`${base}/cash-flow-categories?per=${period}&add=1`}
            className={cn(
              "flex min-h-[120px] items-center justify-center rounded-card border-2 border-dashed border-rule-strong font-medium text-muted no-underline",
              "hover:text-ink phone:min-h-[72px]",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-asset",
            )}
          >
            + New category
          </Link>
        )}
      </div>
    </div>
  );
}

/** The two buttons beside the toggle: 48px pills on desktop; on phones
 * they share a row (stacking on the narrowest). */
const ACTION_BUTTON =
  "min-h-12 px-[22px] phone:min-h-12 phone:flex-[1_1_auto] phone:px-3.5 phone:whitespace-nowrap";

function Headline({ view }: { view: CashFlowsOverview }) {
  const other = `${money(view.other_net, { cents: false })} a ${view.other_period}`;
  const estimates = view.estimates
    ? ` · ≈ ${view.estimates} estimate${view.estimates === 1 ? "" : "s"}`
    : "";
  const over = view.bar_state === "over";
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-[14px] font-medium text-muted">
        {view.short ? "Short" : "Left over"} each {view.period}
      </span>
      <span
        data-slot="headline-figure"
        className={cn(
          "font-display text-[64px] leading-none font-semibold tracking-[-0.03em] [overflow-wrap:anywhere]",
          // "+$19,454.22" stays on one line down to 320px.
          "phone:text-[clamp(32px,11vw,48px)]",
          over && "text-danger",
        )}
      >
        {money(view.net, { sign: true })}
      </span>
      <span className="text-muted [&_strong]:font-semibold [&_strong]:text-ink">
        {over ? (
          <>
            Expenses <strong>{money(view.expenses)}</strong> vs income{" "}
            <strong>{money(view.income)}</strong> · {other}
            {estimates}
          </>
        ) : (
          <>
            of <strong>{money(view.income)}</strong> income · {other}
            {estimates}
          </>
        )}
      </span>
    </div>
  );
}

function WhereIncomeGoes({ view }: { view: CashFlowsOverview }) {
  const over = view.bar_state === "over";
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-[14px]">
        <span className="font-semibold">Where income goes</span>
        {over ? (
          <span className="font-medium text-danger">
            Expenses exceed income by {money(view.over_by ?? "0")} (
            {view.over_share})
          </span>
        ) : (
          <span className="text-muted">
            Expenses {money(view.expenses)}
            {view.expenses_share && ` · ${view.expenses_share}`}
          </span>
        )}
      </div>
      {view.bar_state === "no_income" && (
        <>
          <div className="h-10 rounded-[10px] bg-chip" />
          <p className="text-[13px] text-muted">
            No income yet. Add an income cash flow to see where it goes.
          </p>
        </>
      )}
      {view.bar_state === "normal" && (
        <>
          <Bar
            slices={view.slices}
            label={`Of ${money(view.income)} income each ${view.period}: ${view.slices
              .map((s) => `${s.label} ${s.share}`)
              .join(", ")}`}
          />
          <BarKey>
            {view.slices.map((s) => (
              <li key={`${s.category_id}-${s.label}`} className={KEY_ITEM}>
                <Swatch color={s.color} />
                {s.label} <strong>{money(s.amount)}</strong> {s.share}
              </li>
            ))}
          </BarKey>
        </>
      )}
      {over && <OverBar view={view} />}
    </div>
  );
}

/** Expenses above income (board AA): 100% is all expenses; the marker is
 * where income runs out, and the part past it is hatched. */
function OverBar({ view }: { view: CashFlowsOverview }) {
  const overBy = money(view.over_by ?? "0");
  const marker = { "--marker": `${view.marker}%` } as CSSProperties;
  return (
    <>
      <div className="relative" style={marker}>
        <Bar
          slices={view.slices}
          label={`Expenses of ${money(view.expenses)} each ${view.period}: ${view.slices
            .map((s) => `${s.label} ${money(s.amount)}, `)
            .join(
              "",
            )}against ${money(view.income)} income, which runs out before the last ${overBy}`}
        />
        <span
          aria-hidden="true"
          data-slot="past-income"
          className="absolute -top-1.5 right-0 -bottom-1.5 left-(--marker) rounded-r-xl shadow-[inset_0_0_0_2px_var(--danger)]"
          style={{
            background:
              "repeating-linear-gradient(135deg, transparent 0 6px, color-mix(in srgb, var(--danger) 35%, transparent) 6px 8px)",
          }}
        />
        <span
          aria-hidden="true"
          className="absolute -top-2.5 -bottom-2.5 left-(--marker) -ml-px w-0.5 bg-ink"
        />
      </div>
      <div
        data-slot="marker-label"
        aria-hidden="true"
        className="relative h-[18px] text-[13px]"
        style={marker}
      >
        <span className="absolute left-[clamp(64px,var(--marker),calc(100%-64px))] -translate-x-1/2 font-medium whitespace-nowrap text-ink">
          ▲ Income runs out
        </span>
      </div>
      <BarKey>
        {view.slices.map((s) => (
          <li key={`${s.category_id}-${s.label}`} className={KEY_ITEM}>
            <Swatch color={s.color} />
            {s.label} <strong>{money(s.amount)}</strong>
          </li>
        ))}
        <li className={KEY_ITEM}>
          <span
            className="size-2.5 flex-none rounded-[2px] shadow-[inset_0_0_0_1.5px_var(--danger)]"
            style={{
              background:
                "repeating-linear-gradient(135deg, transparent 0 2px, var(--danger) 2px 3px)",
            }}
          />
          Past income <strong>{overBy}</strong>
        </li>
      </BarKey>
    </>
  );
}

function Bar({ slices, label }: { slices: BarSlice[]; label: string }) {
  return (
    <div
      role="img"
      aria-label={label}
      className="flex h-10 gap-0.5 overflow-hidden rounded-[10px]"
    >
      {slices.map((s) => (
        <span
          key={`${s.category_id}-${s.label}`}
          className="min-w-0.5 shrink-0 basis-0"
          style={{ flexGrow: Number(s.weight), background: s.color }}
        />
      ))}
    </div>
  );
}

function BarKey({ children }: { children: ReactNode }) {
  return (
    <ul className="flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-muted phone:gap-x-4 phone:gap-y-1.5 [&_strong]:font-normal [&_strong]:text-ink">
      {children}
    </ul>
  );
}

const KEY_ITEM = "flex list-none items-center gap-1.5 phone:flex-wrap";

function Swatch({ color }: { color: string }) {
  return (
    <span
      className="size-2.5 flex-none rounded-[2px] shadow-[inset_0_0_0_1px_var(--rule-strong)]"
      style={{ background: color }}
    />
  );
}

/** A row: name (and ≈) over "amount every …", the period's amount right;
 * a hairline between rows. An editor's row is a link to its drawer, the
 * whole row the target. */
const ROW =
  "flex min-h-[52px] items-center justify-between gap-3 border-b border-rule py-1 last:border-b-0";

function FlowCardView({ card, period }: { card: FlowCard; period: Period }) {
  const { base, canEdit } = useWorkspace();
  const income = card.direction === "income";
  const note = income
    ? "All income"
    : card.share
      ? `${card.share} of income`
      : "No income to compare";
  const addQuery = income
    ? "direction=income"
    : "direction=expense" +
      (card.category_id !== null ? `&category_id=${card.category_id}` : "");

  return (
    <Card data-slot="flow-card" className="p-6 phone:p-5">
      <div className="flex items-center justify-between gap-3 pb-2.5">
        <h2 className="flex min-w-0 items-center gap-2.5 font-display text-[18px] font-semibold">
          <span
            className="size-3 flex-none rounded-[3px]"
            style={{ background: card.color }}
          />
          {card.name}
        </h2>
        <span className="font-display text-[18px] font-semibold whitespace-nowrap">
          {money(card.total)}
        </span>
      </div>
      <span className="border-b border-rule-strong pb-2 text-[13px] text-muted">
        {note}
      </span>
      {card.flows.length === 0 && (
        <p className="pt-4 pb-1 text-[13px] text-muted">
          {income ? "No income yet" : "No expenses yet"}
        </p>
      )}
      {card.flows.map((flow) => {
        const inner = (
          <>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span data-slot="flow-name" className="flex items-center gap-2">
                {flow.name}
                {flow.is_estimate && (
                  <>
                    {" "}
                    <EstimateTag />
                  </>
                )}
              </span>
              <span className="text-[13px] text-muted">
                {money(flow.amount)} {flow.every_text}
              </span>
            </span>
            <span className="whitespace-nowrap phone:self-center">
              {money(flow.per_period)}
            </span>
          </>
        );
        return canEdit ? (
          <Link
            key={flow.id}
            data-slot="flow-row"
            to={`${base}/cash-flows/${flow.id}/edit?per=${period}`}
            className={cn(
              ROW,
              "text-ink no-underline hover:[&_[data-slot=flow-name]]:underline",
              "focus-visible:rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-asset",
            )}
          >
            {inner}
          </Link>
        ) : (
          <div key={flow.id} data-slot="flow-row" className={ROW}>
            {inner}
          </div>
        );
      })}
      {canEdit && (
        <Button
          asChild
          variant="secondary"
          className="mt-3 self-start phone:min-h-11 phone:px-5"
        >
          <Link
            to={`${base}/cash-flows/new?${addQuery}&per=${period}`}
            aria-label={`Add to ${card.name}`}
          >
            + Add
          </Link>
        </Button>
      )}
    </Card>
  );
}
