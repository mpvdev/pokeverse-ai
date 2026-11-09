"""The Battle Evaluation Agent: turns engine-detected mistakes into short, cited lessons."""

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field, InstanceOf, create_model

from pokeverse.agents.research import ChatModel
from pokeverse.battles import Mistake
from pokeverse.llm import Completion, OutputSchema, parse_reply
from pokeverse.model import FrozenModel

MAX_LESSONS = 3
REVIEW_MAX_TOKENS = 2000

BATTLE_REVIEW_SYSTEM_PROMPT = (
    "You are the PokéVerse Battle Evaluation Agent. You review mistakes that the game engine "
    "detected in a battle agent's play; each mistake is a fact. Write at most three short, "
    "general lessons that would have prevented them, phrased as rules the agent can apply in "
    "future battles (not about one specific Pokémon unless the pattern is specific). Every "
    "lesson must cite the ids of the mistakes it addresses. Do not invent mistakes."
)


class Lesson(FrozenModel):
    text: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class BattleReview(FrozenModel):
    lessons: tuple[Lesson, ...]
    completion: InstanceOf[Completion] | None = Field(exclude=True)

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


def review_reply_model(ids: list[str]) -> type[FrozenModel]:
    """The reply shape for one review: evidence must be ids of the detected mistakes."""
    lesson = create_model(
        "LessonReply",
        __base__=FrozenModel,
        text=(str, ...),
        evidence=(tuple[Literal[tuple(ids)], ...], ...),
    )
    return create_model(
        "BattleReviewReply", __base__=FrozenModel, lessons=(tuple[lesson, ...], ...)
    )


class BattleReviewAgent:
    def __init__(self, chat: ChatModel, *, max_tokens: int = REVIEW_MAX_TOKENS) -> None:
        self._chat = chat
        self._max_tokens = max_tokens

    def review(self, mistakes: Sequence[Mistake]) -> BattleReview:
        """Lessons that cite at least one detected mistake; no mistakes means no model call."""
        if not mistakes:
            return BattleReview(lessons=(), completion=None)
        ids = mistake_ids(mistakes)
        reply_model = review_reply_model(ids)
        completion = self._chat.complete(
            review_prompt(mistakes),
            system=BATTLE_REVIEW_SYSTEM_PROMPT,
            max_tokens=self._max_tokens,
            output_schema=OutputSchema.from_model("battle_review", reply_model),
        )
        reply: Any = parse_reply(reply_model, completion, "Battle review")
        lessons = tuple(
            Lesson(text=item.text.strip(), evidence=tuple(dict.fromkeys(item.evidence)))
            for item in reply.lessons
        )
        cited = tuple(lesson for lesson in lessons if lesson.text and lesson.evidence)
        return BattleReview(lessons=cited[:MAX_LESSONS], completion=completion)
