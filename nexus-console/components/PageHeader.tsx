import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow?: string;
  /** @deprecated Use eyebrow instead */
  prototypeId?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
};

export function PageHeader({ eyebrow, prototypeId, title, description, actions }: PageHeaderProps) {
  const badge = eyebrow ?? prototypeId;

  return (
    <div className="page-header">
      <div className="page-header-left">
        {badge && <span className="page-header-badge">{badge}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}
