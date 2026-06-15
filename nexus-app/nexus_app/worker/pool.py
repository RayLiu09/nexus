from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from nexus_app.config import Settings, get_settings
from nexus_app.worker.loop import WorkerLoop

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerPoolState:
    enabled: bool
    configured_size: int
    running_threads: int
    worker_ids: list[str]


class WorkerPool:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.size = max(0, int(self.settings.worker_pool_size))
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._loops: list[WorkerLoop] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        if not self.settings.worker_pool_enabled or self.size <= 0:
            logger.info(
                "worker pool disabled enabled=%s size=%s",
                self.settings.worker_pool_enabled,
                self.size,
            )
            return

        with self._lock:
            if self._threads:
                return
            self._stop_event.clear()
            for idx in range(self.size):
                loop = WorkerLoop(
                    worker_id=f"api-worker-{idx + 1}",
                    settings=self.settings,
                    max_concurrent=self.settings.worker_max_concurrent,
                    poll_interval_seconds=self.settings.worker_poll_interval_seconds,
                    lease_seconds=self.settings.worker_lease_seconds,
                )
                thread = threading.Thread(
                    target=self._run_loop,
                    args=(loop,),
                    name=f"nexus-worker-{idx + 1}",
                    daemon=False,
                )
                self._loops.append(loop)
                self._threads.append(thread)
                thread.start()
            logger.info("worker pool started size=%d", self.size)

    def _run_loop(self, loop: WorkerLoop) -> None:
        try:
            loop.run_until_stopped(self._stop_event)
        except Exception:
            logger.exception("worker %s terminated unexpectedly", loop.worker_id)
        finally:
            loop.close()

    def stop(self, timeout: float | None = None) -> None:
        with self._lock:
            threads = list(self._threads)
            self._stop_event.set()
        join_timeout = timeout if timeout is not None else max(1.0, self.settings.worker_poll_interval_seconds + 1.0)
        for thread in threads:
            thread.join(timeout=join_timeout)
        with self._lock:
            alive = [thread for thread in self._threads if thread.is_alive()]
            if alive:
                logger.warning("worker pool stop timed out for %d thread(s)", len(alive))
            self._threads = alive
            self._loops = [loop for loop, thread in zip(self._loops, threads, strict=False) if thread.is_alive()]
            if not alive:
                logger.info("worker pool stopped")

    def state(self) -> WorkerPoolState:
        with self._lock:
            threads = list(self._threads)
            loops = list(self._loops)
        running = [thread for thread in threads if thread.is_alive()]
        return WorkerPoolState(
            enabled=self.settings.worker_pool_enabled,
            configured_size=self.size,
            running_threads=len(running),
            worker_ids=[loop.worker_id for loop, thread in zip(loops, threads, strict=False) if thread.is_alive()],
        )
