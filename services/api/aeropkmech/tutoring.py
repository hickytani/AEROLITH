"""Future tutoring seam. The shipped lesson uses deterministic calculations and written explanations."""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class TutorAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    evidence: list[str] = Field(default_factory=list)
    provider: str
    requires_engineering_validation: bool = True


class TutorProvider(Protocol):
    async def answer(self, question: str, lesson_id: str, calculation_context: dict[str, Any]) -> TutorAnswer: ...


class NoTutorProvider:
    """No network tutor is configured; current learning explanations are deterministic and lesson-authored."""

    async def answer(self, question: str, lesson_id: str, calculation_context: dict[str, Any]) -> TutorAnswer:
        raise RuntimeError("No tutoring model is configured. Use the deterministic lesson explanations and calculations.")
