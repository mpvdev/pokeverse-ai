"""The Opponent Analysis Agent: ranks threats and counters before a battle; code checks them."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pokeverse.agents.research import ChatModel
from pokeverse.battles import Battler, BattleState, matchup
from pokeverse.llm import Completion, LlmRequestError, OutputSchema

ANALYSIS_MAX_TOKENS = 3000
DANGER_LEVELS = ("high", "medium", "low")

OPPONENT_ANALYSIS_SYSTEM_PROMPT = (
    "You are the PokéVerse Opponent Analysis Agent. Before a simplified singles battle you "
    "study the opposing team using a matchup table computed by the game engine: for every "
    "pair, each side's best move, damage as % of HP, hits needed to knock out, who moves "
    "first and who wins one-on-one. Rely on the table; never work out damage or type "
    "effectiveness yourself. Rank every foe exactly once by danger (high, medium, low): how "
    "many of our Pokémon it beats and how hard it is to stop. For each threat worth "
    "answering, name the member of our team that should handle it, preferring members the "
    "table says win that one-on-one. Finish with a short game plan: whom to lead with, whom "
    "to preserve for which threat. Keep reasons to one sentence."
)


def own_id(index: int, battler: Battler) -> str:
    return f"own-{index}:{battler.pokemon.name}"


def foe_id(index: int, battler: Battler) -> str:
    return f"foe-{index}:{battler.pokemon.name}"


def matchup_table(own: Sequence[Battler], foe: Sequence[Battler]) -> str:
    lines = ["Matchup table (our Pokémon first in each line):"]
    for i, ours in enumerate(own):
        for j, theirs in enumerate(foe):
            facts = matchup(ours, theirs).describe()
            lines.append(f"- {own_id(i, ours)} vs {foe_id(j, theirs)}: {facts}")
    return "\n".join(lines)


def analysis_schema(own_ids: list[str], foe_ids: list[str]) -> OutputSchema:
    return OutputSchema(
        name="opponent_analysis",
        schema={
            "type": "object",
            "properties": {
                "threats": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "foe": {"type": "string", "enum": foe_ids},
                            "danger": {"type": "string", "enum": list(DANGER_LEVELS)},
                            "reason": {"type": "string"},
                        },
                        "required": ["foe", "danger", "reason"],
                        "additionalProperties": False,
                    },
                },
                "counters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "threat": {"type": "string", "enum": foe_ids},
                            "answer": {"type": "string", "enum": own_ids},
                            "reason": {"type": "string"},
                        },
                        "required": ["threat", "answer", "reason"],
                        "additionalProperties": False,
                    },
                },
                "plan": {"type": "string"},
            },
            "required": ["threats", "counters", "plan"],
            "additionalProperties": False,
        },
    )


@dataclass(frozen=True, slots=True)
class Threat:
    foe: str
    danger: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"foe": self.foe, "danger": self.danger, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Counter:
    threat: str
    answer: str
    reason: str
    verified: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "threat": self.threat,
            "answer": self.answer,
            "reason": self.reason,
            "verified": self.verified,
        }


def _name(identifier: str) -> str:
    return identifier.split(":", 1)[1].replace("-", " ").title()


def _slot(identifier: str) -> int:
    return int(identifier.split(":", 1)[0].split("-", 1)[1])


@dataclass(frozen=True, slots=True)
class OpponentAnalysis:
    threats: tuple[Threat, ...]
    counters: tuple[Counter, ...]
    plan: str
    completion: Completion

    def briefing(self, state: BattleState | None = None, side: int = 0) -> str:
        """Threat ranking and verified counters, minus anything already knocked out in ``state``."""

        def fainted(owner: int, identifier: str) -> bool:
            return state is not None and state.sides[owner].team[_slot(identifier)].fainted

        ranked = sorted(
            (threat for threat in self.threats if not fainted(1 - side, threat.foe)),
            key=lambda threat: DANGER_LEVELS.index(threat.danger),
        )
        if not ranked:
            return ""
        lines = [
            "Pre-battle analysis (threat ranking by the Opponent Analysis Agent; "
            "counters verified by the engine's one-on-one matchups; knocked-out Pokémon "
            "removed):",
            "- Threats: " + "; ".join(f"{_name(t.foe)} {t.danger}" for t in ranked) + ".",
        ]
        for counter in self.counters:
            if not counter.verified:
                continue
            if fainted(1 - side, counter.threat) or fainted(side, counter.answer):
                continue
            lines.append(
                f"- Keep {_name(counter.answer)} for {_name(counter.threat)}: it wins that "
                "one-on-one."
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threats": [threat.to_dict() for threat in self.threats],
            "counters": [counter.to_dict() for counter in self.counters],
            "plan": self.plan,
        }


class OpponentAnalysisAgent:
    def __init__(self, chat: ChatModel, *, max_tokens: int = ANALYSIS_MAX_TOKENS) -> None:
        self._chat = chat
        self._max_tokens = max_tokens

    def analyze(self, own: Sequence[Battler], foe: Sequence[Battler]) -> OpponentAnalysis:
        own_ids = [own_id(i, battler) for i, battler in enumerate(own)]
        foe_ids = [foe_id(j, battler) for j, battler in enumerate(foe)]
        completion = self._chat.complete(
            matchup_table(own, foe),
            system=OPPONENT_ANALYSIS_SYSTEM_PROMPT,
            max_tokens=self._max_tokens,
            output_schema=analysis_schema(own_ids, foe_ids),
        )
        data = completion.data or {}
        try:
            threats = tuple(
                Threat(item["foe"], item["danger"], item["reason"]) for item in data["threats"]
            )
            ranked = [threat.foe for threat in threats]
            if sorted(ranked) != sorted(foe_ids):
                raise ValueError(f"every foe must be ranked exactly once, got {ranked}")
            counters = tuple(
                Counter(
                    item["threat"],
                    item["answer"],
                    item["reason"],
                    matchup(
                        own[own_ids.index(item["answer"])], foe[foe_ids.index(item["threat"])]
                    ).wins,
                )
                for item in data["counters"]
            )
            plan = data["plan"]
        except (KeyError, TypeError, ValueError) as error:
            raise LlmRequestError(
                f"Opponent analysis failed validation: {error}", completion=completion
            ) from error
        return OpponentAnalysis(threats, counters, plan, completion)
