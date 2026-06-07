"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { App } from "antd";

/**
 * Reusable optimistic mutation hook.
 *
 * Pattern:
 * 1. Capture state snapshot via getSnapshot().
 * 2. Call onMutate(args) to immediately update UI (optimistic).
 * 3. Execute mutationFn(args) — the actual API call.
 * 4a. On success: show successMessage.
 * 4b. On failure: call rollback(snapshot) to restore previous state, show error.
 *
 * Usage:
 * ```
 * const { execute, isPending } = useOptimisticMutation({
 *   mutationFn: (id: string) => deleteApiData(`/api/items/${id}`),
 *   onMutate: (id: string) => {
 *     setItems((prev) => prev.filter((i) => i.id !== id));
 *   },
 *   rollback: (snapshot) => setItems(snapshot as Item[]),
 *   getSnapshot: () => items,
 *   successMessage: "已删除",
 * });
 *
 * // Later:
 * <Button onClick={() => execute(itemId)} loading={isPending}>删除</Button>
 * ```
 */
interface UseOptimisticMutationOptions<TData, TArgs = void> {
  /** The actual async API call. Receives the args passed to execute(). */
  mutationFn: (args: TArgs) => Promise<TData>;
  /** Called immediately before the API call to optimistically update UI. */
  onMutate: (args: TArgs) => void;
  /** Called with the snapshot captured before onMutate, to restore state on failure. */
  rollback: (snapshot: unknown) => void;
  /** Returns a snapshot of the current state before optimistic update. */
  getSnapshot: () => unknown;
  /** Success toast message. Omit to skip. */
  successMessage?: string;
  /** Called after success or failure (cleanup). */
  onSettled?: () => void;
}

interface UseOptimisticMutationResult<TArgs = void> {
  execute: (args: TArgs) => Promise<void>;
  isPending: boolean;
  error: string | null;
}

export function useOptimisticMutation<TData = void, TArgs = void>(
  options: UseOptimisticMutationOptions<TData, TArgs>,
): UseOptimisticMutationResult<TArgs> {
  const { message } = App.useApp();
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  const execute = useCallback(
    async (args: TArgs) => {
      const { mutationFn, onMutate, rollback, getSnapshot, successMessage, onSettled } =
        optionsRef.current;

      const snapshot = getSnapshot();
      setIsPending(true);
      setError(null);

      // Step 1: Optimistic update
      onMutate(args);

      try {
        // Step 2: API call
        await mutationFn(args);

        // Step 3: Success
        if (successMessage) {
          message.success(successMessage);
        }
      } catch (err) {
        // Step 4: Rollback on failure
        const errorMsg = err instanceof Error ? err.message : "操作失败";
        setError(errorMsg);
        message.error(errorMsg);
        rollback(snapshot);
      } finally {
        setIsPending(false);
        onSettled?.();
      }
    },
    [message],
  );

  return { execute, isPending, error };
}
