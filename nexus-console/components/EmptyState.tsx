import type { ReactNode } from "react";

type EmptyStateProps = {
  icon?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
};

export function EmptyState({ icon = "📄", title, description, actions }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon">{icon}</span>
      <strong>{title}</strong>
      {description && <p>{description}</p>}
      {actions && <div style={{ marginTop: "var(--space-3)" }}>{actions}</div>}
    </div>
  );
}
