import Link from "next/link";

const POLICY_LEVELS = [
  { value: "all", label: "全部" },
  { value: "national", label: "国家政策" },
  { value: "provincial", label: "省级政策" },
  { value: "regional", label: "区域政策" },
] as const;

export function PolicyLevelNav({ href, current }: { href: string; current: string }) {
  return (
    <nav
      className="border-line bg-surface inline-grid w-full grid-cols-2 rounded-md border p-1 sm:w-auto sm:grid-cols-4"
      aria-label="政策层级"
    >
      {POLICY_LEVELS.map((level) => {
        const active = current === level.value;
        const target = level.value === "all" ? href : `${href}?policyLevel=${level.value}`;
        return (
          <Link
            key={level.value}
            href={target}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-9 items-center justify-center rounded px-4 text-sm font-medium transition-colors ${
              active
                ? "bg-brand text-text-inverse"
                : "text-text-secondary hover:bg-surface-alt hover:text-text"
            }`}
          >
            {level.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function normalizePolicyLevel(value: string | string[] | undefined): string {
  const candidate = Array.isArray(value) ? value[0] : value;
  return POLICY_LEVELS.some((level) => level.value === candidate) ? candidate! : "all";
}
