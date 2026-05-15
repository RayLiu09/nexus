import { statusDefinitions, type StatusValue } from "@/lib/status";

type StatusLabelProps = {
  value: StatusValue | string;
  /** Override label text */
  label?: string;
};

export function StatusLabel({ value, label }: StatusLabelProps) {
  const status = statusDefinitions[value as StatusValue] ?? {
    label: value,
    tone: "neutral"
  };
  return (
    <span className={`status-label status-label-${status.tone}`}>
      {label ?? status.label}
    </span>
  );
}
