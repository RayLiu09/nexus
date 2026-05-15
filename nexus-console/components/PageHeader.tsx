import type { ReactNode } from "react";

type PageHeaderProps = {
  /** NX prototype ID (e.g. "NX-01") */
  prototypeId: string;
  /** Page title */
  title: string;
  /** Page description / summary */
  description?: string;
  /** Primary action slot (button, link, etc.) */
  actions?: ReactNode;
};

export function PageHeader({ prototypeId, title, description, actions }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div className="page-header-left">
        <span className="page-header-badge">{prototypeId}</span>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}
