"""Deterministic, local-only gateway for execution safety tests.

This adapter is intentionally not imported by the production execution path.
It returns explicitly simulated states and never represents a broker fill.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SimulatedOutcome:
    status: str
    order_id: str | None = None
    error: str | None = None


class TestGateway:
    """Local state machine used only by tests and controlled dry-run checks."""

    __test__ = False

    VALID_STATES = {"accepted", "rejected", "partial", "filled", "timeout", "unknown"}

    def __init__(self, outcome: str = "accepted"):
        if outcome not in self.VALID_STATES:
            raise ValueError("Unsupported simulated gateway outcome")
        self.outcome = outcome
        self.submissions: list[dict[str, Any]] = []
        self._reconciliation: dict[str, str] = {}

    async def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a simulated outcome; never contacts a broker."""
        sequence = len(self.submissions) + 1
        order_id = f"simulated-{sequence}" if self.outcome in {"accepted", "partial", "filled"} else None
        self.submissions.append({"payload": dict(payload), "order_id": order_id})
        if self.outcome == "rejected":
            return {"success": False, "status": "rejected", "order_id": None, "simulated": True}
        if self.outcome == "timeout":
            return {"success": False, "status": "timeout", "order_id": None, "simulated": True}
        if self.outcome == "unknown":
            return {"success": False, "status": "unknown", "order_id": None, "reconciliation_required": True, "simulated": True}
        return {"success": self.outcome == "filled", "status": self.outcome, "order_id": order_id, "simulated": True}

    def set_reconciliation(self, order_id: str, status: str) -> None:
        if status not in {"filled", "rejected", "unknown"}:
            raise ValueError("Unsupported reconciliation state")
        self._reconciliation[str(order_id)] = status

    async def reconcile(self, order_id: str) -> dict[str, Any]:
        status = self._reconciliation.get(str(order_id), "unknown")
        return {
            "success": status in {"filled", "rejected"},
            "status": status,
            "order_id": str(order_id),
            "simulated": True,
            "reconciliation_required": status == "unknown",
        }
