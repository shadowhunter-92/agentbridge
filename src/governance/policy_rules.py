"""
Declarative policy rules — policy engine v2.

The base PolicyEngine enforces identity + capability allowlist + approval + budget.
This adds a composable RULE layer for the policies enterprises actually ask for:

  - cap the cost of any single call            (MaxCostPerCall)
  - require human approval above a cost         (RequireApprovalAboveCost)
  - deny / allow specific capabilities globally (DenyCapabilities / AllowOnlyCapabilities)
  - restrict calls to business hours            (BusinessHoursOnly)
  - block a specific protocol route             (DenyProtocolRoute)

Rules are pure and ordered; the FIRST deny wins. A rule may instead flag NEEDS_APPROVAL.
Everything here is plain Python — no dependencies — and fully unit-tested.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, Set


@dataclass
class PolicyContext:
    agent_id: str
    capability: str
    cost: float = 1.0
    src_protocol: Optional[str] = None
    dst_protocol: Optional[str] = None
    now: Optional[datetime] = None

    def when(self) -> datetime:
        return self.now or datetime.now(timezone.utc)


@dataclass
class RuleResult:
    allowed: bool = True
    reason: str = ""
    needs_approval: bool = False


class Rule(ABC):
    @abstractmethod
    def evaluate(self, ctx: PolicyContext) -> RuleResult: ...


class MaxCostPerCall(Rule):
    def __init__(self, max_cost: float):
        self.max_cost = max_cost

    def evaluate(self, ctx: PolicyContext) -> RuleResult:
        if ctx.cost > self.max_cost:
            return RuleResult(False, f"cost {ctx.cost} exceeds per-call cap {self.max_cost}")
        return RuleResult()


class RequireApprovalAboveCost(Rule):
    def __init__(self, threshold: float):
        self.threshold = threshold

    def evaluate(self, ctx: PolicyContext) -> RuleResult:
        if ctx.cost > self.threshold:
            return RuleResult(True, f"approval required: cost {ctx.cost} > {self.threshold}",
                              needs_approval=True)
        return RuleResult()


class DenyCapabilities(Rule):
    def __init__(self, capabilities: Iterable[str]):
        self.caps: Set[str] = set(capabilities)

    def evaluate(self, ctx: PolicyContext) -> RuleResult:
        if ctx.capability in self.caps:
            return RuleResult(False, f"capability '{ctx.capability}' is denied by policy")
        return RuleResult()


class AllowOnlyCapabilities(Rule):
    def __init__(self, capabilities: Iterable[str]):
        self.caps: Set[str] = set(capabilities)

    def evaluate(self, ctx: PolicyContext) -> RuleResult:
        if ctx.capability not in self.caps:
            return RuleResult(False, f"capability '{ctx.capability}' not in policy allowlist")
        return RuleResult()


class BusinessHoursOnly(Rule):
    """Allow only within [start_hour, end_hour) on the given weekdays (UTC by default).

    days: 0=Mon .. 6=Sun. Default Mon-Fri, 09:00-17:00 UTC.
    """
    def __init__(self, start_hour: int = 9, end_hour: int = 17,
                 days: Optional[Iterable[int]] = None):
        self.start = start_hour
        self.end = end_hour
        self.days: Set[int] = set(days) if days is not None else set(range(0, 5))

    def evaluate(self, ctx: PolicyContext) -> RuleResult:
        t = ctx.when()
        if t.weekday() not in self.days or not (self.start <= t.hour < self.end):
            return RuleResult(
                False,
                f"outside allowed window (days {sorted(self.days)} {self.start:02d}:00-{self.end:02d}:00 UTC)")
        return RuleResult()


class DenyProtocolRoute(Rule):
    def __init__(self, src: str, dst: str):
        self.src = src
        self.dst = dst

    def evaluate(self, ctx: PolicyContext) -> RuleResult:
        if ctx.src_protocol == self.src and ctx.dst_protocol == self.dst:
            return RuleResult(False, f"route {self.src}->{self.dst} is blocked by policy")
        return RuleResult()


class PolicySet:
    """An ordered set of rules. First deny wins; needs_approval is sticky across rules."""

    def __init__(self, rules: Optional[Sequence[Rule]] = None):
        self.rules: List[Rule] = list(rules or [])

    def add(self, rule: Rule) -> "PolicySet":
        self.rules.append(rule)
        return self

    def evaluate(self, ctx: PolicyContext) -> RuleResult:
        needs_approval = False
        approval_reason = ""
        for rule in self.rules:
            r = rule.evaluate(ctx)
            if not r.allowed:
                return r  # first deny wins
            if r.needs_approval:
                needs_approval = True
                approval_reason = r.reason or approval_reason
        return RuleResult(True, approval_reason if needs_approval else "policy ok", needs_approval)
