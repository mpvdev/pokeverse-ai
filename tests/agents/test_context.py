from pokeverse.agents.context import SharedContext, with_context
from pokeverse.llm import ToolCall

PIKACHU = {"pokedex_id": 25, "name": "pikachu", "types": ["electric"]}
GARCHOMP = {"pokedex_id": 445, "name": "garchomp", "types": ["dragon", "ground"]}
CHARIZARD = {"pokedex_id": 6, "name": "charizard", "types": ["fire", "flying"]}
GARCHOMP_MATCHUPS = ToolCall(
    "get_type_matchups",
    {"name_or_id": "Garchomp"},
    {
        "pokemon": GARCHOMP,
        "weak_to": {"ice": 4.0, "dragon": 2.0, "fairy": 2.0},
        "resists": {"fire": 0.5, "poison": 0.5, "rock": 0.5},
        "immune_to": {"electric": 0.0},
    },
)


def test_records_facts_from_all_tool_kinds() -> None:
    context = SharedContext()

    context.record(
        (
            ToolCall("get_pokemon", {"name_or_id": "pikachu"}, PIKACHU),
            GARCHOMP_MATCHUPS,
            ToolCall("analyze_team", {"names": ["charizard"]}, {"team": {"members": [CHARIZARD]}}),
        )
    )

    assert context.names == ("charizard", "garchomp", "pikachu")
    assert context.matchups["garchomp"]["weak_to"]["ice"] == 4.0


def test_error_outputs_are_not_recorded() -> None:
    context = SharedContext()

    context.record(
        (
            ToolCall("get_pokemon", {"name_or_id": "x"}, {"error": "not_found", "message": "x"}),
            ToolCall("analyze_team", {"names": ["x"]}, {"error": "not_found", "message": "x"}),
        )
    )

    assert context.names == ()
    assert context.render() == ""


def test_render_lists_types_and_matchups() -> None:
    context = SharedContext()
    context.record((ToolCall("get_pokemon", {}, PIKACHU), GARCHOMP_MATCHUPS))

    lines = context.render().splitlines()

    assert lines[0].startswith("Verified facts")
    assert lines[1] == (
        "- garchomp (#445): dragon/ground; weak to ice 4x, dragon 2x, fairy 2x; "
        "resists fire 0.5x, poison 0.5x, rock 0.5x; immune to electric"
    )
    assert lines[2] == "- pikachu (#25): electric"


def test_with_context_appends_facts_only_when_present() -> None:
    context = SharedContext()
    assert with_context("Build a team.", context) == "Build a team."

    context.record((ToolCall("get_pokemon", {}, PIKACHU),))

    assert with_context("Build a team.", context).startswith("Build a team.\n\nVerified facts")
