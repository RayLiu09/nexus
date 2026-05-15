/**
 * Data domain tag — maps D1-D6 to v3.2 domain color palette.
 */
type DomainTagProps = {
  domain: string; // "D1" through "D6"
  label?: string;
};

const domainMap: Record<string, { variant: string; defaultLabel: string }> = {
  D1: { variant: "domain-d1", defaultLabel: "D1 教学资源" },
  D2: { variant: "domain-d2", defaultLabel: "D2 人才培养" },
  D3: { variant: "domain-d3", defaultLabel: "D3 科研数据" },
  D4: { variant: "domain-d4", defaultLabel: "D4 产教融合" },
  D5: { variant: "domain-d5", defaultLabel: "D5 政策法规" },
  D6: { variant: "domain-d6", defaultLabel: "D6 综合管理" }
};

export function DomainTag({ domain, label }: DomainTagProps) {
  const entry = domainMap[domain];
  if (!entry) {
    return (
      <span className="tag">
        {label ?? domain}
      </span>
    );
  }
  return (
    <span className={`tag tag-${entry.variant}`}>
      {label ?? entry.defaultLabel}
    </span>
  );
}
