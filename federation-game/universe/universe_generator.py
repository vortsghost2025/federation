"""Procedural Universe Generator for Federation Game.

CPU-only. No third-party deps beyond the Python standard library.
Read-only on existing data; outputs deterministic, seeded JSON that
maps NPC homeworlds to existing sectors and describes procedurally generated
star system details for the new Three.js starmap to render.

Usage:
    python3 universe_generator.py [seed]

Defaults seed=20260623. Same seed -> same universe; deterministic.
"""

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.request
from typing import Any

BACKEND_URL = os.environ.get("FEDERATION_BACKEND_URL", "http://localhost")
HOST_HEADER = os.environ.get("FEDERATION_HOST", "federation-game.deliberatefederation.cloud")

STELLAR_CLASSES = [
    ("O", 16.0, 30000, 0.95), ("B", 2.9, 20000, 0.9), ("A", 2.0, 9000, 0.85),
    ("F", 1.4, 7200, 0.8), ("G", 1.04, 5800, 0.75), ("K", 0.8, 5100, 0.7),
    ("M", 0.45, 3500, 0.6),
]
PLANET_TYPES = [
    "rocky_inner", "sub_neptune", "gas_giant", "ice_giant",
    "ocean_world", "desert_world", "volcanic_world", "tidally_locked",
    "ringed_giant", "carbon_world",
]
BIOMES = [
    "lava_plains", "frozen_dunes", "verdant_continents", "acid_seas",
    "crystal_forests", "bioluminescent_tundra", "magnetically_scrubbed_cliffs",
    "deep_kelp_forest", "salt_flats", "sulfuric_lowlands",
]
RESOURCES = [
    "iron", "copper", "titanium", "pura-ice", "agricultural_mass",
    "silicon", "luminite", "void_crystal", "rare_water", "cobalt",
    "fusion_grade_lithium", "neutron_dust",
]


def _seeded_rng(seed: int):
    s = [seed & 0xFFFFFFFF]
    def f():
        s[0] = (s[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = s[0]
        t = (((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF)
        t = (t ^ (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF))) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0
    return f


def _hash_int(s: str, salt: int) -> int:
    h = hashlib.sha256(f"{salt}::{s}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def _get(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Host": HOST_HEADER},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def fetch_map_data() -> dict[str, Any]:
    return _get(f"{BACKEND_URL}/map/data")


def fetch_sectors(map_data: dict[str, Any]) -> list[dict[str, Any]]:
    return map_data.get("sectors", [])


def fetch_npcs(map_data: dict[str, Any]) -> list[dict[str, Any]]:
    return map_data.get("npcs", [])


def make_universe(seed: int, sectors: list[dict[str, Any]], npcs: list[dict[str, Any]]) -> dict[str, Any]:
    rng = _seeded_rng(seed)
    galaxy: dict[str, Any] = {
        "seed": seed,
        "version": "0.1.0",
        "generated_at": _hash_int("now", seed),
        "sector_count": len(sectors),
        "npc_count": len(npcs),
        "star_systems": {},
        "faction_territory": {},
    }

    for sec in sectors:
        sid = sec["id"]
        seed_salt = _hash_int(sid, seed)
        local = _seeded_rng(seed_salt)
        stellar = STELLAR_CLASSES[math.floor(local() * len(STELLAR_CLASSES))]
        p_count = max(0, min(9, int(local() * 9 * 0.85 + 1)))
        planets = []
        for i in range(p_count):
            p_offset = 0.3 + local() * 18.0
            p_type = PLANET_TYPES[math.floor(local() * len(PLANET_TYPES))]
            biome = BIOMES[math.floor(local() * len(BIOMES))]
            moons = max(0, min(7, int(local() * 6)))
            resources = []
            n_res = max(1, int(local() * 5))
            for _ in range(n_res):
                r = RESOURCES[math.floor(local() * len(RESOURCES))]
                if r not in resources:
                    resources.append(r)
            planets.append({
                "idx": i,
                "orbit_au": round(p_offset, 3),
                "type": p_type,
                "biome": biome,
                "moons": moons,
                "resources": resources,
                "habitable": p_type in ("ocean_world", "rocky_inner", "tidally_locked")
                             and local() > 0.5,
            })
        galaxy["star_systems"][sid] = {
            "id": sid,
            "name": sec["name"],
            "x": sec["x"], "y": sec["y"],
            "region_type": sec["region_type"],
            "resource_profile": sec.get("resource_profile", "-"),
            "danger_level": sec["danger_level"],
            "star": {
                "class": stellar[0],
                "mass_solar": stellar[1],
                "temperature_k": stellar[2],
                "luminosity_factor": stellar[3],
            },
            "planets": planets,
            "adjacent_sector_ids": sec.get("adjacent_sector_ids", []),
            "narrative_seed": seed_salt,
        }

    faction_to_sector = {}
    for npc in (npcs or []):
        faction = npc.get("affiliation") or npc.get("faction") or "orbital_free"
        cid = npc.get("char_id") or npc.get("id") or "unknown"
        target_idx = _hash_int(cid, seed) % max(1, len(sectors))
        if 0 <= target_idx < len(sectors):
            sid = sectors[target_idx]["id"]
            faction_to_sector.setdefault(faction, {"sectors": set(), "members": []})
            faction_to_sector[faction]["sectors"].add(sid)
            faction_to_sector[faction]["members"].append({
                "char_id": cid,
                "name": npc.get("name", "Unknown"),
                "role": npc.get("role", ""),
            })
    galaxy["faction_territory"] = {
        k: {"sectors": sorted(list(v["sectors"])), "members": v["members"]}
        for k, v in faction_to_sector.items()
    }

    return galaxy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("seed", nargs="?", default=20260623, type=int)
    parser.add_argument("--out", default="/docker/federation-game/universe/universe.json")
    parser.add_argument("--out-sectors",
                        default="/docker/federation-game/universe/sector_seed.json")
    args = parser.parse_args()

    print(f"Fetching map data from {BACKEND_URL}/map/data ...")
    map_data = fetch_map_data()
    sectors = fetch_sectors(map_data)
    npcs = fetch_npcs(map_data)
    print(f"  -> {len(sectors)} sectors, {len(npcs)} NPCs")

    print(f"Generating universe with seed {args.seed} ...")
    galaxy = make_universe(args.seed, sectors, npcs)
    galaxy["sectors"] = sectors

    out_dir = os.path.dirname(args.out)
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(galaxy, f, indent=2, sort_keys=True)
    print(f"Wrote universe to {args.out} ({os.path.getsize(args.out)} bytes; "
          f"{len(sectors)} sectors, {len(npcs)} NPCs)")

    with open(args.out_sectors, "w") as f:
        json.dump({
            "seed": args.seed,
            "sectors": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "x": s["x"], "y": s["y"],
                    "region_type": s["region_type"],
                    "danger_level": s["danger_level"],
                }
                for s in sectors
            ],
        }, f, indent=2)
    print(f"Wrote sector seed to {args.out_sectors} "
          f"({os.path.getsize(args.out_sectors)} bytes)")


if __name__ == "__main__":
    sys.exit(main())
