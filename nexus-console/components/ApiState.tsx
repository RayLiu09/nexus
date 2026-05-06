type ApiStateProps = {
  ok: boolean;
  error: string | null;
  traceId?: string | null;
};

export function ApiState({ ok, error, traceId }: ApiStateProps) {
  return (
    <div className={`api-state ${ok ? "api-state-ok" : "api-state-error"}`}>
      <span>{ok ? "真实 API 已连接" : "真实 API 不可用"}</span>
      {error ? <strong>{error}</strong> : null}
      {traceId ? <span className="mono-cell">trace_id: {traceId}</span> : null}
    </div>
  );
}
