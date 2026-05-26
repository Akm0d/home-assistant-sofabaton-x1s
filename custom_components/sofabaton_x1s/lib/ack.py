"""Typed outcomes for hub ack waits.

Every ``wait_for_*`` site distinguishes three states:

* ``acked``    -- the hub answered, and the answer was a success ack.
* ``rejected`` -- the hub answered explicitly, but the answer was a
  rejection (e.g. ``STATUS_ACK`` carrying a non-zero status byte).
* ``timeout``  -- the hub did not answer within the wait window.

Conflating the latter two leads to fail-slow behaviour during multi-step
sequences: the orchestration spins out the full per-step timeout rather
than aborting at the first hub-side refusal. The dataclasses below give
callers a uniform way to branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AckOutcome(Enum):
    """Three-way classification of an ack wait."""

    acked = "acked"
    rejected = "rejected"
    timeout = "timeout"


@dataclass(frozen=True, slots=True)
class SendStepResult:
    """Outcome of a single ``_send_step`` exchange."""

    outcome: AckOutcome
    ack_opcode: int | None = None
    ack_payload: bytes | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is AckOutcome.acked

    @property
    def rejected(self) -> bool:
        return self.outcome is AckOutcome.rejected

    @property
    def timed_out(self) -> bool:
        return self.outcome is AckOutcome.timeout


@dataclass(frozen=True, slots=True)
class InputsBurstResult:
    """Outcome of :meth:`X1Proxy.wait_for_activity_inputs_burst`.

    ``payloads`` is populated on :attr:`AckOutcome.acked` and is empty
    on rejection or timeout.
    """

    outcome: AckOutcome
    payloads: tuple[bytes, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome is AckOutcome.acked

    @property
    def rejected(self) -> bool:
        return self.outcome is AckOutcome.rejected

    @property
    def timed_out(self) -> bool:
        return self.outcome is AckOutcome.timeout


__all__ = [
    "AckOutcome",
    "InputsBurstResult",
    "SendStepResult",
]
