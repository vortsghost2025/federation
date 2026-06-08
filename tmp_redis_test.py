import redis, json
r = redis.Redis(host="redis", port=6379, decode_responses=True)
for key in ["world_state", "npc_adapter:prev_world_state"]:
    data = r.get(key)
    print(f"KEY {key} exists: {data is not None}")
    if data:
        try:
            obj = json.loads(data)
            print(f"  {key} top-level keys: {list(obj.keys())[:10]}")
        except Exception as e:
            print(f"  {key} is not valid JSON: {e}")
for prefix in ["npc_quests:stats:", "fed:"]:
    keys = r.keys(prefix + "*")
    print(f"Prefix {prefix} matches {len(keys)} keys; sample: {keys[:5]}")
