import { statusDefinitions, type StatusValue } from "@/lib/status";

type StatusLabelProps = {
  value: StatusValue;
};

export function StatusLabel({ value }: StatusLabelProps) {
  const status = statusDefinitions[value];
  return <span className={`status-label status-label-${status.tone}`}>{status.label}</span>;
}
