"""The Team Optimization Agent: the model proposes, deterministic code decides.

The model extracts type claims from a team's notes and proposes swaps. Our code checks each
claim against the type chart and keeps a swap only if it strictly improves the team's score.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pokeverse.agents.research import ChatModel
from pokeverse.agents.tools import (
    make_catalog_tools,
    make_score_tool,
    normalize_identifier,
)
from pokeverse.catalog import (
    PokemonCatalog,
    PokemonNotInCatalogError,
    PokemonType,
    UpstreamUnavailableError,
)
from pokeverse.catalog.models import NAME_PATTERN
from pokeverse.catalog.type_chart import effectiveness
from pokeverse.llm import Completion, LlmRequestError, OutputSchema
from pokeverse.teams import Team, TeamAnalysis, analyze_team

MAX_SWAPS = 3
MAX_CANDIDATES = 5
OPTIMIZER_MAX_TOOL_ROUNDS = 8
# Reasoning tokens count against this limit, and the reply lists claims, swaps and a critique.
OPTIMIZER_MAX_TOKENS = 3000
VERDICTS = ("weak", "resists", "immune", "neutral")

OPTIMIZER_SYSTEM_PROMPT = (
    "You are the PokéVerse Team Optimization Agent. You review a team you did not build. "
    "1) In `claims`, list every type-matchup claim the author's notes make about a specific "
    "member (e.g. 'Corviknight resists Ice' -> member corviknight, attacking_type ice, "
    "claimed resists). Only extract claims; do not judge them. Use an empty list if there are "
    "none. "
    f"2) Propose up to {MAX_SWAPS} swaps that improve the analysis, in this order of "
    "importance: fewer vulnerabilities, fewer members exposed to them, fewer unresisted types, "
    "fewer offensive gaps. Respect the goal, and never swap out a member listed under Keep. "
    f"Test candidate teams with score_team (at most {MAX_CANDIDATES} candidates) before "
    "proposing them. Swaps are applied in order, "
    "each to the result of the previous one, and a swap that does not improve the team is "
    "rejected automatically, so propose none if nothing helps. "
    "3) In `critique`, briefly explain the team's main problem and your swaps. "
    "Use canonical names as returned by the tools."
)

_SLUG = {"type": "string", "pattern": f"^{NAME_PATTERN.pattern}$"}
OPTIMIZATION_SCHEMA = OutputSchema(
    name="team_optimization",
    schema={
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "member": _SLUG,
                        "attacking_type": {
                            "type": "string",
                            "enum": [t.value for t in PokemonType],
                        },
                        "claimed": {"type": "string", "enum": list(VERDICTS)},
                    },
                    "required": ["member", "attacking_type", "claimed"],
                    "additionalProperties": False,
                },
            },
            "swaps": {
                "type": "array",
                "maxItems": MAX_SWAPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "out": _SLUG,
                        "in": _SLUG,
                        "reason": {"type": "string"},
                    },
                    "required": ["out", "in", "reason"],
                    "additionalProperties": False,
                },
            },
            "critique": {"type": "string"},
        },
        "required": ["claims", "swaps", "critique"],
        "additionalProperties": False,
    },
)


def verdict(multiplier: float) -> str:
    if multiplier == 0:
        return "immune"
    if multiplier > 1:
        return "weak"
    return "resists" if multiplier < 1 else "neutral"


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    member: str
    attacking_type: str
    claimed: str
    # None when the Pokémon could not be found, so the claim could not be checked.
    actual: str | None
    multiplier: float | None

    @property
    def correct(self) -> bool:
        return self.claimed == self.actual

    def to_dict(self) -> dict[str, Any]:
        return {
            "member": self.member,
            "attacking_type": self.attacking_type,
            "claimed": self.claimed,
            "actual": self.actual,
            "multiplier": self.multiplier,
            "correct": self.correct,
        }


@dataclass(frozen=True, slots=True)
class SwapDecision:
    out: str
    into: str
    reason: str
    accepted: bool
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "out": self.out,
            "in": self.into,
            "reason": self.reason,
            "accepted": self.accepted,
            "verdict": self.verdict,
        }


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    original: TeamAnalysis
    final: TeamAnalysis
    swaps: tuple[SwapDecision, ...]
    claims: tuple[ClaimCheck, ...]
    critique: str
    completion: Completion

    @property
    def incorrect_claims(self) -> tuple[ClaimCheck, ...]:
        return tuple(claim for claim in self.claims if not claim.correct)

    def to_dict(self) -> dict[str, Any]:
        final = self.final.to_dict()
        del final["exposures"]
        return {
            "original_members": list(self.original.team.names),
            "original_score": list(self.original.score),
            "final_members": list(self.final.team.names),
            "final_score": list(self.final.score),
            "final_analysis": final,
            "swaps": [swap.to_dict() for swap in self.swaps],
            "claims": [claim.to_dict() for claim in self.claims],
            "critique": self.critique,
        }


def _prompt(analysis: TeamAnalysis, goal: str, keep: Sequence[str], notes: str, facts: str) -> str:
    summary = analysis.to_dict()
    del summary["exposures"]
    lines = [
        f"Team: {', '.join(analysis.team.names)}",
        f"Goal: {goal or 'none given'}",
        f"Keep: {', '.join(keep) or 'none'}",
        f"Current analysis: {summary}",
        f"Author's notes:\n{notes or 'none'}",
    ]
    if facts:
        lines.append(f"\n{facts}\n(These verified facts are not claims to extract.)")
    return "\n".join(lines)


class TeamOptimizationAgent:
    """Reviews a team: checks its type claims and applies only swaps that measurably help."""

    def __init__(self, chat: ChatModel, catalog: PokemonCatalog) -> None:
        self._chat = chat
        self._catalog = catalog
        self._tools = make_catalog_tools(catalog) + (make_score_tool(catalog),)

    def optimize(
        self,
        team: Team,
        *,
        goal: str = "",
        keep: Sequence[str] = (),
        notes: str = "",
        facts: str = "",
    ) -> OptimizationResult:
        keep_names = {normalize_identifier(name) for name in keep}
        original = analyze_team(team)
        completion = self._chat.complete(
            _prompt(original, goal, sorted(map(str, keep_names)), notes, facts),
            system=OPTIMIZER_SYSTEM_PROMPT,
            max_tokens=OPTIMIZER_MAX_TOKENS,
            tools=self._tools,
            output_schema=OPTIMIZATION_SCHEMA,
            max_tool_rounds=OPTIMIZER_MAX_TOOL_ROUNDS,
        )
        try:
            data = completion.data or {}
            claims = tuple(self._check_claim(team, claim) for claim in data["claims"])
            proposed = [(s["out"], s["in"], s["reason"]) for s in data["swaps"]][:MAX_SWAPS]
            critique = data["critique"]
        except (KeyError, TypeError, ValueError) as error:
            raise LlmRequestError(
                f"Model reply failed validation: {error}", completion=completion
            ) from error

        current = original
        decisions = []
        for out, into, reason in proposed:
            decision, current = self._try_swap(current, out, into, reason, keep_names)
            decisions.append(decision)
        return OptimizationResult(original, current, tuple(decisions), claims, critique, completion)

    def _check_claim(self, team: Team, claim: dict[str, str]) -> ClaimCheck:
        member = next((m for m in team.members if m.name == claim["member"]), None)
        if member is None:
            try:
                member = self._catalog.get(normalize_identifier(claim["member"]))
            except PokemonNotInCatalogError, UpstreamUnavailableError:
                member = None
        multiplier = (
            effectiveness(PokemonType(claim["attacking_type"]), member.types) if member else None
        )
        return ClaimCheck(
            member=claim["member"],
            attacking_type=claim["attacking_type"],
            claimed=claim["claimed"],
            actual=verdict(multiplier) if multiplier is not None else None,
            multiplier=multiplier,
        )

    def _try_swap(
        self, current: TeamAnalysis, out: str, into: str, reason: str, keep: set[Any]
    ) -> tuple[SwapDecision, TeamAnalysis]:
        def reject(why: str) -> tuple[SwapDecision, TeamAnalysis]:
            return SwapDecision(out, into, reason, False, why), current

        names = list(current.team.names)
        if out in keep:
            return reject("the user asked to keep this member")
        if out not in names:
            return reject("not on the team")
        try:
            newcomer = self._catalog.get(normalize_identifier(into))
        except (PokemonNotInCatalogError, UpstreamUnavailableError, ValueError) as error:
            return reject(f"could not look up {into!r}: {error}")
        members = list(current.team.members)
        members[names.index(out)] = newcomer
        candidate = analyze_team(Team(members=tuple(members)))
        if candidate.score >= current.score:
            return reject(f"no improvement: score {current.score} -> {candidate.score}")
        verdict_text = f"improved: score {current.score} -> {candidate.score}"
        return SwapDecision(out, into, reason, True, verdict_text), candidate
