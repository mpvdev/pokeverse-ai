"""Battle evaluation: win rate, mistakes and cost of battle players on fixed scenarios."""

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pokeverse.agents import (
    BattleReview,
    BattleReviewAgent,
    BattleStrategyAgent,
    OpponentAnalysisAgent,
)
from pokeverse.agents.research import ChatModel
from pokeverse.battles import (
    Battler,
    GreedyPlayer,
    Mistake,
    Player,
    RecordingPlayer,
    find_mistakes,
    run_battle,
)

BATTLE_SYSTEMS = ("greedy", "agent", "agent+analysis")
LLM_SYSTEMS = ("agent", "agent+analysis", "agent+lessons")


@dataclass(frozen=True, slots=True)
class BattleScenario:
    id: str
    side1: tuple[str, ...]
    side2: tuple[str, ...]
    description: str


BATTLE_SCENARIOS = (
    BattleScenario(
        "bulk",
        ("garchomp", "pikachu", "charizard"),
        ("tyranitar", "gyarados", "snorlax"),
        "Fast attackers against a bulky team that greedy play loses to.",
    ),
    BattleScenario(
        "starters",
        ("venusaur", "charizard", "blastoise"),
        ("lucario", "gengar", "dragonite"),
        "Kanto starters against a faster, mixed team.",
    ),
)


def wilson_interval(wins: int, battles: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a win rate; honest for small samples, unlike p +/- 2 s.e."""
    if battles == 0:
        return 0.0, 1.0
    p = wins / battles
    denominator = 1 + z * z / battles
    centre = (p + z * z / (2 * battles)) / denominator
    half = z * math.sqrt(p * (1 - p) / battles + z * z / (4 * battles * battles)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True, slots=True)
class BattleRecord:
    seed: int
    winner: int | None
    turns: int
    tokens: int
    fallbacks: int
    mistakes: tuple[Mistake, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "winner": self.winner,
            "turns": self.turns,
            "tokens": self.tokens,
            "fallbacks": self.fallbacks,
            "mistakes": [mistake.to_dict() for mistake in self.mistakes],
        }


@dataclass(frozen=True, slots=True)
class SystemReport:
    """Side 1 played by ``system`` against a greedy side 2."""

    system: str
    records: tuple[BattleRecord, ...]
    setup_tokens: int = 0

    @property
    def battles(self) -> int:
        return len(self.records)

    @property
    def wins(self) -> int:
        return sum(record.winner == 0 for record in self.records)

    @property
    def draws(self) -> int:
        return sum(record.winner is None for record in self.records)

    @property
    def win_rate(self) -> float:
        return self.wins / self.battles if self.battles else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.wins, self.battles)

    @property
    def mistakes(self) -> tuple[Mistake, ...]:
        return tuple(mistake for record in self.records for mistake in record.mistakes)

    @property
    def mistakes_per_battle(self) -> float:
        return len(self.mistakes) / self.battles if self.battles else 0.0

    @property
    def total_tokens(self) -> int:
        return self.setup_tokens + sum(record.tokens for record in self.records)

    @property
    def tokens_per_battle(self) -> float:
        return self.total_tokens / self.battles if self.battles else 0.0

    @property
    def average_turns(self) -> float:
        return sum(r.turns for r in self.records) / self.battles if self.battles else 0.0

    @property
    def fallbacks(self) -> int:
        return sum(record.fallbacks for record in self.records)

    def to_dict(self) -> dict[str, Any]:
        low, high = self.interval
        return {
            "system": self.system,
            "battles": self.battles,
            "wins": self.wins,
            "draws": self.draws,
            "win_rate": self.win_rate,
            "win_rate_95": [low, high],
            "average_turns": self.average_turns,
            "mistakes_per_battle": self.mistakes_per_battle,
            "tokens_per_battle": self.tokens_per_battle,
            "total_tokens": self.total_tokens,
            "fallbacks": self.fallbacks,
            "records": [record.to_dict() for record in self.records],
        }


def run_system(
    system: str,
    team: Sequence[Battler],
    opponent: Sequence[Battler],
    seeds: Sequence[int],
    chat: ChatModel | None = None,
    *,
    lessons: str = "",
    progress: Callable[[str], None] | None = None,
) -> SystemReport:
    if system not in (*BATTLE_SYSTEMS, "agent+lessons"):
        raise ValueError(f"unknown system {system!r}; choose from {', '.join(BATTLE_SYSTEMS)}")
    if system in LLM_SYSTEMS and chat is None:
        raise ValueError(f"system {system!r} needs an LLM client")

    analysis = None
    setup_tokens = 0
    if system == "agent+analysis":
        assert chat is not None
        analysis = OpponentAnalysisAgent(chat).analyze(team, opponent)
        setup_tokens = analysis.completion.total_tokens

    records = []
    for seed in seeds:
        agent = None
        inner: Player = GreedyPlayer()
        if system in LLM_SYSTEMS:
            assert chat is not None
            agent = BattleStrategyAgent(chat, analysis=analysis, lessons=lessons)
            inner = agent
        player = RecordingPlayer(inner)
        result = run_battle(team, opponent, (player, GreedyPlayer()), random.Random(seed))
        record = BattleRecord(
            seed=seed,
            winner=result.winner,
            turns=result.turns,
            tokens=agent.total_tokens if agent else 0,
            fallbacks=agent.fallbacks if agent else 0,
            mistakes=find_mistakes(player.choices),
        )
        records.append(record)
        if progress:
            outcome = {0: "won", 1: "lost", None: "draw"}[record.winner]
            progress(
                f"{system} seed {seed}: {outcome} in {record.turns} turns, "
                f"{len(record.mistakes)} mistakes, {record.tokens} tokens"
            )
    return SystemReport(system, tuple(records), setup_tokens)


@dataclass(frozen=True, slots=True)
class FeedbackReport:
    training: SystemReport
    review: BattleReview
    baseline: SystemReport | None
    with_lessons: SystemReport | None

    @property
    def review_tokens(self) -> int:
        return self.review.completion.total_tokens if self.review.completion else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "training": self.training.to_dict(),
            "review": self.review.to_dict(),
            "review_tokens": self.review_tokens,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "with_lessons": self.with_lessons.to_dict() if self.with_lessons else None,
        }


def feedback_experiment(
    team: Sequence[Battler],
    opponent: Sequence[Battler],
    chat: ChatModel,
    train_seeds: Sequence[int],
    test_seeds: Sequence[int],
    *,
    progress: Callable[[str], None] | None = None,
) -> FeedbackReport:
    """Learn lessons from mistakes on training seeds; compare with and without on test seeds.

    With no lessons there is nothing to compare, so the test battles are skipped.
    """
    if set(train_seeds) & set(test_seeds):
        raise ValueError("training and test seeds must not overlap")
    training = run_system("agent", team, opponent, train_seeds, chat, progress=progress)
    review = BattleReviewAgent(chat).review(training.mistakes)
    if not review.lessons:
        return FeedbackReport(training, review, None, None)
    baseline = run_system("agent", team, opponent, test_seeds, chat, progress=progress)
    with_lessons = run_system(
        "agent+lessons",
        team,
        opponent,
        test_seeds,
        chat,
        lessons=review.guidance(),
        progress=progress,
    )
    return FeedbackReport(training, review, baseline, with_lessons)
