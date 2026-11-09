"""The Battle Evaluation Agent: turns engine-detected mistakes into short, cited lessons."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pokeverse.agents.research import ChatModel
from pokeverse.battles import Mistake
from pokeverse.llm import Completion, LlmRequestError, OutputSchema

MAX_LESSONS = 3
REVIEW_MAX_TOKENS = 2000

BATTLE_REVIEW_SYSTEM_PROMPT = (
    "You are the PokéVerse Battle Evaluation Agent. You review mistakes that the game engine "
    "detected in a battle agent's play; each mistake is a fact. Write at most three short, "
    "general lessons that would have prevented them, phrased as rules the agent can apply in "
    "future battles (not about one specific Pokémon unless the pattern is specific). Every "
    "lesson must cite the ids of the mistakes it addresses. Do not invent mistakes."
)


@dataclass(frozen=True, slots=True)
class Lesson:
    text: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "evidence": list(self.evidence)}


@dataclass(frozen=True, slots=True)
class BattleReview:
    lessons: tuple[Lesson, ...]
    completion: Completion | None

    def guidance(self) -> str:
        if not self.lessons:
            return ""
        lines = ["Lessons from earlier battles (each based on mistakes the engine detected):"]
        lines.extend(f"- {lesson.text}" for lesson in self.lessons)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"lessons": [lesson.to_dict() for lesson in self.lessons]}


def mistake_ids(mistakes: Sequence[Mistake]) -> list[str]:
    return [f"m-{index}" for index in range(len(mistakes))]


def review_prompt(mistakes: Sequence[Mistake]) -> str:
    lines = ["Mistakes detected by the engine:"]
    for identifier, mistake in zip(mistake_ids(mistakes), mistakes, strict=True):
        lines.append(f"- {identifier} [{mistake.kind}]: {mistake.describe()}")
    return "\n".join(lines)


def review_schema(ids: list[str]) -> OutputSchema:
    return OutputSchema(
        name="battle_review",
        schema={
            "type": "object",
            "properties": {
                "lessons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "evidence": {
                                "type": "array",
                                "items": {"type": "string", "enum": ids},
                            },
                        },
                        "required": ["text", "evidence"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["lessons"],
            "additionalProperties": False,
        },
    )


class BattleReviewAgent:
    def __init__(self, chat: ChatModel, *, max_tokens: int = REVIEW_MAX_TOKENS) -> None:
        self._chat = chat
        self._max_tokens = max_tokens

    def review(self, mistakes: Sequence[Mistake]) -> BattleReview:
        """Lessons that cite at least one detected mistake; no mistakes means no model call."""
        if not mistakes:
            return BattleReview((), None)
        ids = mistake_ids(mistakes)
        completion = self._chat.complete(
            review_prompt(mistakes),
            system=BATTLE_REVIEW_SYSTEM_PROMPT,
            max_tokens=self._max_tokens,
            output_schema=review_schema(ids),
        )
        try:
            items = (completion.data or {})["lessons"]
            lessons = tuple(
                Lesson(item["text"].strip(), tuple(dict.fromkeys(item["evidence"])))
                for item in items
            )
        except (KeyError, TypeError, AttributeError) as error:
            raise LlmRequestError(
                f"Battle review failed validation: {error}", completion=completion
            ) from error
        cited = tuple(
            lesson
            for lesson in lessons
            if lesson.text and lesson.evidence and set(lesson.evidence) <= set(ids)
        )
        return BattleReview(cited[:MAX_LESSONS], completion)
