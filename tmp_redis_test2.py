import redis
r = redis.Redis(host="redis", port=6379, decode_responses=True)
for key in ["world_state", "npc_adapter:prev_world_state"]:
    t = r.type(key)
    print(f"KEY {key} type: {t}")
    if t == "string":
        data = r.get(key)
        print(f"  {key} length: {len(data) if data else 0}")
    elif t == "hash":
        print(f"  {key} fields: {list(r.hkeys(key))[:10]}")
    elif t == "none":
        print(f"  {key} does not exist")
for prefix in ["npc_quests:stats:", "fed:"]:
    keys = r.keys(prefix + "*")
    print(f"Prefix {prefix} matches {len(keys)} keys; sample: {keys[:5]}")
