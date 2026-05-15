from federation_game_npcs import build_npc_system

# Create NPC system and register sample characters
npc_system = build_npc_system()

print(
    "✓ NPC System initialized - registered %d characters" % len(npc_system.characters)
)

# Show NPCs
print("\nNPC System Status:")
all_npcs = (
    list(npc_system.characters.values()) if hasattr(npc_system, "characters") else []
)
total_npcs = len(all_npcs)
print("  Total Character Players: %d" % total_npcs)

for npc in all_npcs:
    if hasattr(npc, "title") and hasattr(npc, "name"):
        title = getattr(npc, "title", "Unknown")
        name = getattr(npc, "name", "Unknown")
        print(f"    - {name} ({title})")
