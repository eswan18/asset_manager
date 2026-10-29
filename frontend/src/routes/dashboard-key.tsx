import type { BarSegment, CategoryTotal, Kind } from "@/api/dashboard";
import { COLUMN_TITLES, money } from "@/lib/dashboard";
import { cn } from "@/lib/utils";

/**
 * The key under the chart: each side's categories with their amounts. On a
 * phone each side's stacked bar (the column on its side, both on one scale)
 * sits over its key, and the bar's title stands for the key's, which stays
 * for screen readers (the bars are aria-hidden).
 */
export function CategoryKey({
  categories,
  bars,
}: {
  categories: Record<Kind, CategoryTotal[]>;
  bars: Record<Kind, BarSegment[]>;
}) {
  const kinds = (["asset", "liability"] as const).filter(
    (kind) => categories[kind].length > 0 || bars[kind].length > 0,
  );
  if (kinds.length === 0) return null;
  return (
    <div
      data-category-key=""
      className={cn(
        "flex flex-wrap justify-end gap-x-10 gap-y-2 pt-2 text-[13px] text-muted",
        "phone:flex-col phone:flex-nowrap phone:gap-3 phone:pt-0",
      )}
    >
      {kinds.map((kind) => (
        <div key={kind} className="contents">
          {bars[kind].length > 0 && (
            <div
              aria-hidden="true"
              data-category-bar={kind}
              className={cn(
                "hidden items-center gap-2.5 text-[13px] font-semibold text-ink",
                "phone:grid phone:grid-cols-[76px_minmax(0,1fr)]",
                kind === "liability" && "phone:mt-3",
              )}
            >
              <span>{COLUMN_TITLES[kind]}</span>
              <span className="flex h-3 overflow-hidden rounded-[3px] bg-chip">
                {bars[kind].map((s) => (
                  <span
                    key={s.key}
                    data-bar-segment=""
                    title={s.label}
                    className="h-full flex-none border-r-2 border-surface last:border-r-0"
                    style={{ width: `${s.share}%`, background: s.color }}
                  />
                ))}
              </span>
            </div>
          )}
          {categories[kind].length > 0 && (
            <div
              data-key-group={kind}
              className="flex flex-wrap gap-x-6 gap-y-2 phone:gap-x-4 phone:gap-y-1.5"
            >
              <span className="font-semibold text-ink phone:sr-only">
                {COLUMN_TITLES[kind]}
              </span>
              {categories[kind].map((c) => (
                <span key={c.key} className="flex items-center gap-1.5">
                  <span
                    data-swatch=""
                    className="size-2.5 flex-none rounded-xs"
                    style={{ background: c.color }}
                  />
                  {c.label} {money(c.amount)}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
