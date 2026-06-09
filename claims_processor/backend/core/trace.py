"""
Trace builder for claims pipeline observability.
Every component appends entries here; the final result carries the full audit log.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from core.models import TraceEntry, TraceStatus


class TraceBuilder:
    """
    Thread-unsafe, single-claim scoped trace accumulator.
    Passed through the pipeline so all components append to the same log.
    """

    def __init__(self) -> None:
        self._entries: List[TraceEntry] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def info(self, component: str, step: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add(component, step, TraceStatus.INFO, detail, data)

    def passed(self, component: str, step: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add(component, step, TraceStatus.PASS, detail, data)

    def failed(self, component: str, step: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add(component, step, TraceStatus.FAIL, detail, data)

    def warn(self, component: str, step: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add(component, step, TraceStatus.WARN, detail, data)

    def error(self, component: str, step: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add(component, step, TraceStatus.ERROR, detail, data)

    @contextmanager
    def span(self, component: str, step: str) -> Generator[None, None, None]:
        """Context manager that records timing and auto-emits PASS or ERROR."""
        start = datetime.utcnow()
        try:
            yield
            elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
            self._add(component, step, TraceStatus.PASS, f"Completed in {elapsed_ms}ms")
        except Exception as exc:
            elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
            self._add(component, step, TraceStatus.ERROR, f"Failed after {elapsed_ms}ms: {exc!s}")
            raise

    def entries(self) -> List[TraceEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _add(
        self,
        component: str,
        step: str,
        status: TraceStatus,
        detail: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._entries.append(
            TraceEntry(
                component=component,
                step=step,
                status=status,
                detail=detail,
                data=data,
                timestamp=datetime.utcnow(),
            )
        )
