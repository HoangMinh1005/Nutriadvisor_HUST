"""Typed schemas for the NLP engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TrainingExample:
    """Single labeled example used to train the intent classifier."""

    text: str
    intent: str


@dataclass
class NLPResult:
    """Normalized NLP output returned by the intent engine."""

    intent: str
    confidence: float
    entities: dict[str, Any] = field(default_factory=dict)
    source: str = "local"
    raw_response: str | None = None
    cached_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": float(self.confidence),
            "entities": self.entities,
            "source": self.source,
            "raw_response": self.raw_response,
            "cached_from": self.cached_from,
        }


@dataclass(frozen=True)
class ProfileUpdates:
    """Structured profile updates extracted from user text."""

    full_name: str | None = None
    gender: str | None = None
    birth_year: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    weight_goal: str | None = None
    daily_calorie_target: int | None = None


@dataclass(frozen=True)
class ReplacementTarget:
    """Structured food replacement target extracted from user text."""

    food_name: str | None = None
    nutrients: tuple[str, ...] = ()
