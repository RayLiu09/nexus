import { statusDefinitions, type StatusValue } from "@/lib/status";

type StatusLabelProps = {
  value: StatusValue | string;
};

export function StatusLabel({ value }: StatusLabelProps) {
  const status = statusDefinitions[value as StatusValue] ?? {
    label: value,
    tone: "neutral"
  };
  return <span className={`status-label status-label-${status.tone}`}>{status.label}</span>;
}
