"""
test_worldwright_schema.py — Durable regression tests for the Phase 2A.1
Worldwright validator. Pure: no redis, fs, net, env, subprocess, or model.

Run:  python -m pytest federation-game/backend/test_worldwright_schema.py
Or:   python federation-game/backend/test_worldwright_schema.py
"""

import sys
import os

# Make the module importable when run directly from backend/ or repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import worldwright_schema as ww  # noqa: E402


def _base(**over):
    p = {
        "creator_id": ww.WORLDWRIGHT_ARCHITECT,
        "action": "propose_planet",
        "object_type": "planet",
        "name": "Aurora Prime",
        "description": "A temperate world with twin moons.",
        "importance": 0.8,
        "tags": ["habitable", "twin-moons"],
    }
    p.update(over)
    return p


def test_valid_architect_planet():
    r = ww.validate_proposal(_base())
    assert r["valid"] is True
    assert r["code"] == "OK"
    assert r["proposal"]["object_type"] == "planet"
    assert r["proposal"]["discovery_status"] == "undiscovered"
    assert r["proposal"]["creator_role"] == "architect"


def test_valid_architect_region_with_parent():
    r = ww.validate_proposal(_base(
        action="propose_region", object_type="region",
        name="Verdant Expanse", parent_ref="aurora-prime",
    ))
    assert r["valid"] is True
    assert r["proposal"]["parent_ref"] == "aurora-prime"


def test_architect_site_rejected():
    r = ww.validate_proposal(_base(
        action="propose_site", object_type="site",
        name="Hidden Ruin", parent_ref="verdant-expanse",
    ))
    assert r["valid"] is False
    assert r["code"] == "REJECT_ROLE_TYPE_MISMATCH"


def test_valid_shaper_site():
    r = ww.validate_proposal(_base(
        creator_id=ww.WORLDWRIGHT_SHAPER,
        action="propose_site", object_type="site",
        name="Crystal Falls", parent_ref="verdant-expanse",
    ))
    assert r["valid"] is True
    assert r["proposal"]["creator_role"] == "shaper"
    assert r["proposal"]["parent_ref"] == "verdant-expanse"


def test_shaper_planet_rejected():
    r = ww.validate_proposal(_base(
        creator_id=ww.WORLDWRIGHT_SHAPER,
        action="propose_planet", object_type="planet",
        name="Forbidden World",
    ))
    assert r["valid"] is False
    assert r["code"] == "REJECT_ROLE_TYPE_MISMATCH"


def test_unknown_creator_rejected():
    r = ww.validate_proposal(_base(creator_id="char_001"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_UNKNOWN_CREATOR"


def test_unknown_creator_char_307():
    r = ww.validate_proposal(_base(creator_id="char_307"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_UNKNOWN_CREATOR"


def test_missing_parent_rejected():
    r = ww.validate_proposal(_base(
        action="propose_region", object_type="region", name="No Parent",
    ))
    assert r["valid"] is False
    assert r["code"] == "REJECT_MISSING_PARENT"


def test_duplicate_normalized_name_deterministic():
    # Same normalized name -> identical accepted output (deterministic).
    a = ww.validate_proposal(_base(name="Aurora  Prime!"))
    b = ww.validate_proposal(_base(name="aurora-prime"))
    assert a["valid"] and b["valid"]
    assert a["proposal"]["name"] == b["proposal"]["name"] == "aurora-prime"


def test_invalid_importance_low():
    r = ww.validate_proposal(_base(importance=-0.1))
    assert r["valid"] is False
    assert r["code"] == "REJECT_IMPORTANCE_RANGE"


def test_invalid_importance_high():
    r = ww.validate_proposal(_base(importance=1.5))
    assert r["valid"] is False
    assert r["code"] == "REJECT_IMPORTANCE_RANGE"


def test_excessive_name_length():
    r = ww.validate_proposal(_base(name="x" * 200))
    assert r["valid"] is False
    assert r["code"] == "REJECT_NAME_TOO_LONG"


def test_excessive_description_length():
    r = ww.validate_proposal(_base(description="y" * 2000))
    assert r["valid"] is False
    assert r["code"] == "REJECT_DESC_TOO_LONG"


def test_excessive_body_length():
    r = ww.validate_proposal(_base(body="z" * 5000))
    assert r["valid"] is False
    assert r["code"] == "REJECT_BODY_TOO_LONG"


def test_forbidden_shell():
    r = ww.validate_proposal(_base(description="run this: exec(shell cmd)"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_code():
    r = ww.validate_proposal(_base(description="please write_code for planet"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_git():
    r = ww.validate_proposal(_base(description="see github.com/foo/bar"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_deployment():
    r = ww.validate_proposal(_base(description="deploy via docker then restart service"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_credentials():
    r = ww.validate_proposal(_base(description="use api_key secret token to auth"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_model_routing():
    r = ww.validate_proposal(_base(description="switch primary_model to fallback_model"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_external_tools():
    r = ww.validate_proposal(_base(description="call webhook external_api now"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_agent_creation():
    r = ww.validate_proposal(_base(description="create_agent spawn_npc new_npc here"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_redis():
    r = ww.validate_proposal(_base(description="write with rpush r.hset to redis"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_out_of_world_scope_faction_ownership():
    r = ww.validate_proposal(_base(faction_id="fac_001"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_OUT_OF_WORLD_SCOPE"


def test_out_of_world_scope_settled():
    r = ww.validate_proposal(_base(settled=True))
    assert r["valid"] is False
    assert r["code"] == "REJECT_OUT_OF_WORLD_SCOPE"


def test_action_whitelist_only():
    # Blacklist approach would strip write_code; whitelist rejects unknown actions.
    r = ww.validate_proposal(_base(action="write_code"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_ACTION_NOT_ALLOWED"
    # Confirm whitelist contents.
    assert ww.ALLOWED_ACTIONS == {
        "no_action", "propose_planet", "propose_region",
        "propose_site", "revise_rejected_proposal",
    }


def test_no_action_rejected():
    r = ww.validate_proposal(_base(action="no_action"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_NO_ACTION"


def test_revise_has_no_object():
    r = ww.validate_proposal(_base(action="revise_rejected_proposal"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_REVISE_HAS_NO_OBJECT"


def test_input_not_mutated():
    raw = _base(name="Aurora  Prime!", tags=["Habitable"])
    before = dict(raw)
    r = ww.validate_proposal(raw)
    assert r["valid"] is True
    # normalized name lives only in the returned proposal, not the input.
    assert raw["name"] == "Aurora  Prime!"
    assert raw["tags"] == ["Habitable"]
    assert raw == before


def test_deterministic_output_and_codes():
    r1 = ww.validate_proposal(_base())
    r2 = ww.validate_proposal(_base())
    assert r1 == r2
    # Every reject code is deterministic and present in catalogue.
    for code in ww.REJECT_CODES:
        assert isinstance(code, str) and code.startswith("REJECT_")


def test_non_object_input():
    r = ww.validate_proposal("not a dict")
    assert r["valid"] is False
    assert r["code"] == "REJECT_NOT_OBJECT"


def test_missing_required_field():
    p = _base()
    del p["description"]
    r = ww.validate_proposal(p)
    assert r["valid"] is False
    assert r["code"] == "REJECT_MISSING_FIELD"


def test_lore_no_false_positive_secret():
    # "secret cavern" / "token of gratitude" are lore, not credential claims.
    r = ww.validate_proposal(_base(description="a secret cavern hides a token of gratitude"))
    assert r["valid"] is True


def test_lore_no_false_positive_shell():
    # "energy shell" / "seashell" are lore words, not shell execution.
    r = ww.validate_proposal(_base(name="Seashell Reef", description="an energy shell surrounds the planet"))
    assert r["valid"] is True


def test_forbidden_shell_command_still_caught():
    r = ww.validate_proposal(_base(description="drop to shell and run shell command"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_forbidden_credentials_still_caught():
    r = ww.validate_proposal(_base(description="use client_secret and access_token to auth"))
    assert r["valid"] is False
    assert r["code"] == "REJECT_FORBIDDEN_AUTHORITY"


def test_importance_rounded_immutable():
    r = ww.validate_proposal(_base(importance=0.81234))
    assert r["valid"] is True
    assert r["proposal"]["importance"] == 0.8123


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa
            failed += 1
            print(f"ERROR {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
