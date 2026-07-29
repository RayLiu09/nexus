/** Safe, stable identifier for an API Caller credential in the Console. */
export function formatApiCallerKeyReference(
  callerKey: string | null,
  callerKeyHash: string | null,
): string {
  if (callerKeyHash) {
    return `sha256:${callerKeyHash.slice(0, 12)}...${callerKeyHash.slice(-8)}`;
  }
  if (callerKey) {
    const prefix = callerKey.slice(0, 3);
    const suffix = callerKey.slice(-4);
    return `${prefix}...${suffix}`;
  }
  return "-";
}
