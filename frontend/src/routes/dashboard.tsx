import { lazy, Suspense } from "react";
import { Link, useSearchParams } from "react-router";

import {
  parseRange,
  useDashboard,
  type Dashboard,
  type DashboardCard,
  type RangeKey,
} from "@/api/dashboard";
import {
  useDocumentTitle,
  useWorkspace,
} from "@/components/shell/workspace-context";
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
import { SegmentedControl } from "@/components/ui/segmented-control";
import { ComputedTag } from "@/components/ui/tag";
import {
  longDate,
  money,
  shortDate,
  signedMoney,
  signedPercent,
} from "@/lib/dashboard";
import { cn } from "@/lib/utils";

import { CategoryKey } from "./dashboard-key";

// Recharts is most of the app's size: the chart loads on its own, after the
// page, and the card keeps its height while it does.
const NetWorthChart = lazy(() =>
  import("./dashboard-chart").then((m) => ({ default: m.NetWorthChart })),
);

/** `/workspaces/:workspaceId?range=6m|1y|all` (dashboard.html): net worth,
 * its change and the chart over the range, then the account cards; before
 * the first snapshot, the getting-started state (board Y). Changing the
 * range updates the URL without a reload and keeps the old range's numbers
 * on screen until the new ones arrive. */
export function DashboardPage() {
  const workspace = useWorkspace();
  const [params, setParams] = useSearchParams();
  const range = parseRange(params.get("range"));
  const dashboard = useDashboard(workspace.id, range);
  useDocumentTitle(workspace.name);

  if (dashboard.isPending) return null;
  if (dashboard.isError) {
    return (
      <div
        role="alert"
        className="mb-4 rounded-[14px] bg-danger-tint px-[18px] py-3.5 text-[14px] text-danger"
      >
        An error occurred while loading your data. Please try again later.
      </div>
    );
  }
  const data = dashboard.data;
  if (!data.has_data) return <GettingStarted data={data} />;

  const changeRange = (next: RangeKey) =>
    setParams(
      (current) => {
        const updated = new URLSearchParams(current);
        updated.set("range", next);
        return updated;
      },
      { preventScrollReset: true },
    );

  return (
    <div className="fade-in flex flex-col gap-4">
      <Card
        aria-label="Net worth"
        className="gap-8 p-8 phone:gap-6 phone:px-4 phone:py-6"
      >
        <Headline data={data} />
        <div
          className="flex flex-col gap-3"
          aria-busy={dashboard.isPlaceholderData || undefined}
        >
          <div className="flex flex-wrap items-center justify-between gap-3 phone:gap-4">
            <LineKey />
            <SegmentedControl
              label="Range"
              options={data.ranges.map((r) => ({
                value: r.key,
                label: r.label,
              }))}
              value={range}
              onValueChange={changeRange}
              // On a phone, the toggle spans the card in equal segments.
              className="phone:w-full phone:[&>*]:flex-1"
            />
          </div>
          <Suspense fallback={<div className="h-[320px] phone:h-[240px]" />}>
            <NetWorthChart
              history={data.history}
              categories={data.categories}
            />
          </Suspense>
          <CategoryKey categories={data.categories} bars={data.bars} />
        </div>
      </Card>

      <CardGrid>
        {data.cards.map((card) => (
          <AccountCard key={card.kind} card={card} />
        ))}
      </CardGrid>
    </div>
  );
}

function Headline({ data }: { data: Dashboard }) {
  const { base } = useWorkspace();
  const change = data.change;
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1.5">
        <span className="text-[14px] font-medium text-muted">Net worth</span>
        <span
          data-net-worth=""
          className="font-display text-[64px] leading-none font-semibold tracking-[-0.03em] phone:text-[44px]"
        >
          {money(data.net_worth ?? "0")}
        </span>
        {change && (
          <span className="text-muted">
            <strong className="font-semibold text-ink">
              {signedMoney(change.amount)}
              {change.percent !== null && ` (${signedPercent(change.percent)})`}
            </strong>{" "}
            since {shortDate(change.since, data.last_snapshot ?? change.since)}
          </span>
        )}
      </div>
      <div
        className={cn(
          "flex flex-wrap items-center gap-4",
          // On a phone: the date over a button that spans the card.
          "phone:w-full phone:flex-col phone:items-stretch phone:gap-3",
        )}
      >
        <span className="text-[14px] text-muted">
          Last snapshot {data.last_snapshot && longDate(data.last_snapshot)}
        </span>
        <Button
          asChild
          variant="primary"
          className="min-h-12 px-[22px] text-[15px] phone:min-h-12 phone:w-full"
        >
          <Link to={`${base}/accounts`}>Update balances</Link>
        </Button>
      </div>
    </div>
  );
}

const LINE_KEY = [
  { label: "Assets", swatch: "bg-asset" },
  { label: "Net worth", swatch: "bg-ink" },
  { label: "Liabilities", swatch: "bg-liability" },
];

function LineKey() {
  return (
    <div className="flex flex-wrap gap-5 text-[13px] text-muted phone:gap-x-3.5 phone:gap-y-2">
      {LINE_KEY.map((line) => (
        <span key={line.label} className="flex items-center gap-1.5">
          <span className={cn("h-[3px] w-4 rounded-xs", line.swatch)} />
          {line.label}
        </span>
      ))}
    </div>
  );
}

/** The Assets or Liabilities card: every active account under its
 * category, with the latest snapshot's amount (— with none). Before the
 * first snapshot it lists the accounts already added, or says what goes
 * there and (for editors) offers to add one. */
function AccountCard({
  card,
  onboarding = false,
  canEdit = false,
}: {
  card: DashboardCard;
  onboarding?: boolean;
  canEdit?: boolean;
}) {
  const { base } = useWorkspace();
  return (
    <Card kind={card.kind}>
      <CardHead className="items-baseline">
        <CardTitle>{card.title}</CardTitle>
        <CardTools>
          <CardTotal className={cn(onboarding && "text-muted")}>
            {card.total === null ? "—" : money(card.total)}
          </CardTotal>
        </CardTools>
      </CardHead>
      {card.groups.map((group) => (
        <div key={group.key} data-group={group.key}>
          <CardGroupHead
            label={group.label}
            total={onboarding ? undefined : money(group.total)}
          />
          <div>
            {group.accounts.map((account) => (
              <CardRow key={account.id} className="min-h-11">
                <span className="flex flex-wrap items-center gap-2">
                  {account.name}
                  {account.computed && <ComputedTag text={account.computed} />}
                </span>
                <span>
                  {account.amount === null ? "—" : money(account.amount)}
                </span>
              </CardRow>
            ))}
          </div>
        </div>
      ))}
      {card.groups.length === 0 &&
        (onboarding ? (
          <>
            <p className="pt-3 pb-0.5 text-[15px] text-muted">{card.empty}</p>
            {canEdit && card.add && (
              <Button
                asChild
                variant="outline"
                className="mt-2 self-start phone:self-stretch"
              >
                <Link to={`${base}${card.add.path}`}>{card.add.label}</Link>
              </Button>
            )}
          </>
        ) : (
          <p className="px-8 py-16 text-center text-muted">
            No active {card.title.toLowerCase()}.
          </p>
        ))}
    </Card>
  );
}

/** No snapshot yet (board Y): the three steps, a placeholder chart, and the
 * cards with any accounts already added. Viewers get no buttons, and a line
 * saying an editor hasn't started. */
function GettingStarted({ data }: { data: Dashboard }) {
  const { name, base } = useWorkspace();
  const onboarding = data.onboarding;
  const canEdit = data.can_edit;
  return (
    <div className="fade-in flex flex-col gap-4">
      <Card
        aria-labelledby="welcome-heading"
        className={cn(
          "grid grid-cols-[repeat(auto-fit,minmax(min(100%,360px),1fr))] items-center gap-10 p-10",
          "phone:gap-6 phone:px-4 phone:py-7",
        )}
      >
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <span className="text-[14px] font-medium text-muted">
              {name} is new
            </span>
            <h1
              id="welcome-heading"
              className="font-display text-[40px] leading-[1.1] font-semibold tracking-[-0.02em] phone:text-[28px]"
            >
              Let's get your first net worth on the board.
            </h1>
          </div>
          <ol className="list-none">
            {onboarding?.steps.map((step, i) => (
              <li
                key={step.title}
                data-done={step.done || undefined}
                className="grid grid-cols-[36px_minmax(0,1fr)] gap-3.5 border-t border-rule py-4"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex size-8 items-center justify-center rounded-full bg-chip font-display font-semibold",
                    step.done && "bg-asset-tint text-asset",
                  )}
                >
                  {step.done ? "✓" : i + 1}
                </span>
                <span className="flex flex-col items-start gap-1">
                  <strong className="font-semibold">{step.title}</strong>
                  <span className="text-[14px] text-muted">{step.text}</span>
                  {step.action && canEdit && (
                    <Button
                      asChild
                      variant="primary"
                      className="mt-2 min-h-11 px-[22px]"
                    >
                      <Link to={`${base}${step.action.path}`}>
                        {step.action.label}
                      </Link>
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ol>
          {!canEdit && (
            <p className="text-[14px] text-muted">
              {onboarding?.has_accounts
                ? "An editor hasn't entered any balances yet."
                : "An editor hasn't added any accounts yet."}
            </p>
          )}
        </div>
        <PlaceholderChart />
      </Card>

      <CardGrid>
        {data.cards.map((card) => (
          <AccountCard
            key={card.kind}
            card={card}
            onboarding
            canEdit={canEdit}
          />
        ))}
      </CardGrid>
    </div>
  );
}

/** Where the line will be: a dashed curve from a dot, on the chart's grid. */
function PlaceholderChart() {
  return (
    <div
      aria-hidden="true"
      data-placeholder-chart=""
      className="relative h-[340px] overflow-hidden rounded-2xl bg-chip phone:h-[200px]"
    >
      <svg
        viewBox="0 0 400 300"
        preserveAspectRatio="none"
        className="absolute inset-6 h-[calc(100%-48px)] w-[calc(100%-48px)]"
      >
        <g className="stroke-grid" strokeWidth={1}>
          {[60, 140, 220].map((y) => (
            <line
              key={y}
              x1={0}
              y1={y}
              x2={400}
              y2={y}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </g>
        <path
          className="fill-none stroke-rule-strong"
          strokeWidth={3}
          d="M0 230 C 80 220, 140 200, 200 170 S 320 110, 400 80"
          strokeDasharray="8 8"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {/* Where the line starts: 230 of the drawing's 300 units down. */}
      <span
        className="absolute left-[17px] size-3.5 rounded-full bg-asset"
        style={{ top: "calc(24px + (100% - 48px) * 230 / 300 - 7px)" }}
      />
      <span className="absolute bottom-5 left-6 text-[13px] text-muted">
        Your first snapshot starts the line.
      </span>
    </div>
  );
}
