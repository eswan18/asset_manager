import {
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import type { CategoryTotal, Kind, Point } from "@/api/dashboard";
import {
  axisMoney,
  COLUMN_TITLES,
  dateDomain,
  dateTicks,
  dayValue,
  longDate,
  money,
  moneyScale,
  type DateTick,
} from "@/lib/dashboard";
import { cn } from "@/lib/utils";

/**
 * The dashboard's chart (charts.py's figure and dashboard.html's script, in
 * Recharts). Desktop: the assets, net worth and liabilities lines, then a
 * dashed divider, then the latest snapshot's categories as two stacked
 * columns on the same dollar scale, so each column meets its line's end.
 * Phones: the lines only, across the whole width; the columns become the
 * stacked bars in <CategoryKey>. Every color names a token (the categories'
 * come from the API as `var(--asset)` or a `color-mix()` of tokens), so the
 * browser re-themes the chart with the page and no script resolves them.
 */

const PHONE_QUERY = "(max-width: 600px)";

function subscribePhone(onChange: () => void) {
  const query = window.matchMedia(PHONE_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** Whether the screen is a phone (the one breakpoint), live. */
function useIsPhone(): boolean {
  return useSyncExternalStore(
    subscribePhone,
    () => window.matchMedia(PHONE_QUERY).matches,
    () => false,
  );
}

/** An element's width, kept current. 0 until measured (and in jsdom). */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

// charts.py's layout: heights, margins, and where the lines end and the
// columns begin, as fractions of the plot's width (the chart less the dollar
// labels). Below NARROW_BELOW px, the columns take a larger share.
const DESKTOP = { height: 320, top: 8, bottom: 32, left: 56 };
const PHONE = { height: 240, top: 8, bottom: 32, left: 48, right: 12 };
const WIDE = { lines: 0.8, divider: 0.83, columns: 0.86 };
const NARROW = { lines: 0.62, divider: 0.67, columns: 0.72 };
const NARROW_BELOW = 600;

const LINES = [
  { key: "assets", name: "Assets", color: "var(--asset)", width: 2 },
  { key: "net_worth", name: "Net worth", color: "var(--ink)", width: 3 },
  {
    key: "liabilities",
    name: "Liabilities",
    color: "var(--liability)",
    width: 2,
  },
] as const;

const TICK = { fill: "var(--muted)", fontSize: 12 };
const AXIS_LINE = { stroke: "var(--rule-strong)" };

interface LineRow {
  t: number;
  point: Point;
  assets: number;
  liabilities: number;
  net_worth: number;
}

const CHART_LABEL =
  "Assets, net worth and liabilities over time, with the latest snapshot's assets and liabilities by category";

/** The chart: lines (and on desktop, the columns), as wide as its card. */
export function NetWorthChart({
  history,
  categories,
}: {
  history: Point[];
  categories: Record<Kind, CategoryTotal[]>;
}) {
  const phone = useIsPhone();
  const [ref, width] = useWidth<HTMLDivElement>();
  const height = phone ? PHONE.height : DESKTOP.height;

  const rows: LineRow[] = history.map((point) => ({
    t: dayValue(point.date),
    point,
    assets: Number(point.assets),
    liabilities: Number(point.liabilities),
    net_worth: Number(point.net_worth),
  }));
  // One scale for the lines and the columns (their tops meet the lines' ends).
  const columnTotals = (["asset", "liability"] as const).map((kind) =>
    categories[kind].reduce((sum, c) => sum + Number(c.amount), 0),
  );
  const y = moneyScale([
    ...rows.flatMap((r) => [r.assets, r.liabilities, r.net_worth]),
    ...columnTotals,
  ]);

  return (
    <div
      ref={ref}
      role="img"
      aria-label={CHART_LABEL}
      data-chart={phone ? "phone" : "desktop"}
      className={cn(
        "relative w-full",
        // A tap or click leaves no focus ring; the keyboard still gets one.
        "[&_.recharts-surface:focus:not(:focus-visible)]:outline-none",
        // A date's year, under its first tick, may reach below the frame.
        "[&_.recharts-surface]:overflow-visible",
      )}
      style={{ height }}
    >
      {width > 0 &&
        (phone ? (
          <Lines rows={rows} y={y} width={width} phone />
        ) : (
          <DesktopChart
            rows={rows}
            y={y}
            width={width}
            categories={categories}
          />
        ))}
    </div>
  );
}

type Scale = ReturnType<typeof moneyScale>;

function DesktopChart({
  rows,
  y,
  width,
  categories,
}: {
  rows: LineRow[];
  y: Scale;
  width: number;
  categories: Record<Kind, CategoryTotal[]>;
}) {
  const narrow = width < NARROW_BELOW;
  const split = narrow ? NARROW : WIDE;
  const plot = width - DESKTOP.left;
  const linesWidth = DESKTOP.left + split.divider * plot;
  const plotHeight = DESKTOP.height - DESKTOP.top - DESKTOP.bottom;
  return (
    <div className="flex h-full">
      <Lines
        rows={rows}
        y={y}
        width={linesWidth}
        rightMargin={(split.divider - split.lines) * plot}
        ticks={narrow ? 3 : 6}
      />
      {/* From the top of the plot to a little under its axis. */}
      <span
        aria-hidden="true"
        data-divider=""
        className="absolute border-l border-dashed border-rule-strong"
        style={{
          left: linesWidth,
          top: DESKTOP.top,
          bottom: DESKTOP.bottom - 0.08 * plotHeight,
        }}
      />
      <Columns
        categories={categories}
        y={y}
        width={width - linesWidth}
        leftMargin={(split.columns - split.divider) * plot}
        labels={!narrow}
      />
    </div>
  );
}

function Lines({
  rows,
  y,
  width,
  phone = false,
  rightMargin = 0,
  ticks,
}: {
  rows: LineRow[];
  y: Scale;
  width: number;
  phone?: boolean;
  rightMargin?: number;
  ticks?: number;
}) {
  const frame = phone ? PHONE : DESKTOP;
  const domain = dateDomain(rows.map((r) => r.point.date));
  let xTicks = dateTicks(domain, ticks ?? (width < 300 ? 3 : 4));
  if (phone) {
    // Phone labels start at their tick: leave out one too near the right
    // edge to fit ("Oct 2026" is about 56px).
    const plot = width - PHONE.left - PHONE.right;
    xTicks = xTicks.filter(
      (t) => ((domain[1] - t.value) / (domain[1] - domain[0])) * plot >= 56,
    );
  }
  const tickFor = new Map(xTicks.map((t) => [t.value, t]));
  // A lone point draws no line, so give it a dot.
  const lone = rows.length === 1;
  return (
    <LineChart
      width={width}
      height={frame.height}
      data={rows}
      margin={{
        top: frame.top,
        bottom: 0,
        left: 0,
        right: phone ? PHONE.right : rightMargin,
      }}
    >
      <CartesianGrid
        vertical={false}
        horizontalValues={y.ticks}
        stroke="var(--grid)"
      />
      <XAxis
        dataKey="t"
        type="number"
        scale="time"
        domain={domain}
        ticks={xTicks.map((t) => t.value)}
        interval={0}
        height={frame.bottom}
        tickLine={false}
        axisLine={AXIS_LINE}
        // On a phone, dates start at their tick, so the first clears $0.
        tick={(props: TickProps) => (
          <DateTickLabel {...props} tick={tickFor} start={phone} />
        )}
      />
      <YAxis
        width={frame.left}
        domain={y.domain}
        ticks={y.ticks}
        interval={0}
        tickFormatter={axisMoney}
        tick={TICK}
        tickLine={false}
        axisLine={false}
      />
      <Tooltip
        content={LinesTooltip}
        cursor={AXIS_LINE}
        isAnimationActive={false}
      />
      {LINES.map((line) => (
        <Line
          key={line.key}
          dataKey={line.key}
          name={line.name}
          type="linear"
          stroke={line.color}
          strokeWidth={line.width}
          dot={lone ? { r: 3, fill: line.color, stroke: line.color } : false}
          activeDot={{
            r: 4,
            fill: line.color,
            stroke: "var(--surface)",
            strokeWidth: 2,
          }}
          isAnimationActive={false}
        />
      ))}
    </LineChart>
  );
}

interface TickProps {
  x?: number | string;
  y?: number | string;
  payload?: { value: number };
}

function DateTickLabel({
  x,
  y,
  payload,
  tick,
  start,
}: TickProps & { tick: Map<number, DateTick>; start: boolean }) {
  const found = payload && tick.get(payload.value);
  if (!found) return null;
  return (
    <text
      x={Number(x)}
      y={Number(y)}
      dy={8}
      data-x-tick=""
      textAnchor={start ? "start" : "middle"}
      {...TICK}
    >
      <tspan x={Number(x)}>{found.label}</tspan>
      {found.sub && (
        <tspan x={Number(x)} dy={13}>
          {found.sub}
        </tspan>
      )}
    </text>
  );
}

function Columns({
  categories,
  y,
  width,
  leftMargin,
  labels,
}: {
  categories: Record<Kind, CategoryTotal[]>;
  y: Scale;
  width: number;
  leftMargin: number;
  labels: boolean;
}) {
  const kinds = ["asset", "liability"] as const;
  const data = kinds.map((kind) => ({
    kind,
    name: COLUMN_TITLES[kind],
    ...Object.fromEntries(
      categories[kind].map((c) => [`${kind}:${c.key}`, Number(c.amount)]),
    ),
  }));
  return (
    <BarChart
      width={width}
      height={DESKTOP.height}
      data={data}
      margin={{ top: DESKTOP.top, bottom: 0, left: leftMargin, right: 0 }}
      // Bars 0.7 of their slot, as the figure's.
      barCategoryGap="15%"
    >
      <CartesianGrid
        vertical={false}
        horizontalValues={y.ticks}
        stroke="var(--grid)"
      />
      <XAxis
        dataKey="name"
        height={DESKTOP.bottom}
        tickLine={false}
        axisLine={AXIS_LINE}
        tick={labels ? TICK : false}
        interval={0}
      />
      <YAxis hide domain={y.domain} ticks={y.ticks} />
      <Tooltip
        content={(props) => (
          <ColumnsTooltip {...props} categories={categories} />
        )}
        cursor={false}
        isAnimationActive={false}
      />
      {/* Largest first, so it sits at the bottom of its column. */}
      {kinds.flatMap((kind) =>
        categories[kind].map((c) => (
          <Bar
            key={`${kind}:${c.key}`}
            dataKey={`${kind}:${c.key}`}
            name={c.label}
            stackId="columns"
            fill={c.color}
            stroke="var(--surface)"
            strokeWidth={2}
            isAnimationActive={false}
          />
        )),
      )}
    </BarChart>
  );
}

/** The hover label's frame (Plotly's hoverlabel: surface, a strong rule). */
function TooltipFrame({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div
      data-chart-tooltip=""
      className="rounded-md border border-rule-strong bg-surface px-2.5 py-1.5 text-[13px] text-ink shadow-menu"
    >
      <div className="font-semibold">{title}</div>
      {children}
    </div>
  );
}

function TooltipRow({
  color,
  label,
  amount,
  swatch,
}: {
  color: string;
  label: string;
  amount: string;
  swatch: "line" | "block";
}) {
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap">
      <span
        aria-hidden="true"
        className={cn(
          "flex-none",
          swatch === "line" ? "h-[3px] w-3 rounded-sm" : "size-2.5 rounded-xs",
        )}
        style={{ background: color }}
      />
      <span>{label}</span>
      <span className="ml-auto pl-3 font-semibold">{amount}</span>
    </div>
  );
}

/** One date's three values (Plotly's "x unified"). */
function LinesTooltip({ active, payload }: TooltipContentProps) {
  const row = payload?.[0]?.payload as LineRow | undefined;
  if (!active || !row) return null;
  return (
    <TooltipFrame title={longDate(row.point.date)}>
      {LINES.map((line) => (
        <TooltipRow
          key={line.key}
          color={line.color}
          label={line.name}
          amount={money(row.point[line.key])}
          swatch="line"
        />
      ))}
    </TooltipFrame>
  );
}

/** A column's categories, top of the stack first. */
function ColumnsTooltip({
  active,
  payload,
  categories,
}: TooltipContentProps & {
  categories: Record<Kind, CategoryTotal[]>;
}) {
  const kind = (payload?.[0]?.payload as { kind?: Kind } | undefined)?.kind;
  if (!active || !kind) return null;
  return (
    <TooltipFrame title={COLUMN_TITLES[kind]}>
      {[...categories[kind]].reverse().map((c) => (
        <TooltipRow
          key={c.key}
          color={c.color}
          label={c.label}
          amount={money(c.amount)}
          swatch="block"
        />
      ))}
    </TooltipFrame>
  );
}
