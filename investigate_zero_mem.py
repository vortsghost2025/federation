import redis, json, time

r = redis.Redis.from_url('redis://redis:6379/0', decode_responses=True)

focus = ['comp_007', 'comp_006', 'comp_009', 'char_204', 'char_303', 'char_401', 'char_001']

print('=' * 70)
print('HIGH-VISIBLE ZERO-MEMORY NPC INVESTIGATION')
print('=' * 70)

for cid in focus:
    print(f'\n{"=" * 50}')
    print(f'NPC: {cid}')
    print(f'{"=" * 50}')
    
    # 1. memory keys
    mem_key = f'npc_memory:{cid}'
    mem_zc = r.zcard(mem_key) if r.exists(mem_key) else 0
    print(f'npc_memory:{cid} zcard: {mem_zc}')
    
    summ_key = f'npc_memory_summary:{cid}'
    print(f'npc_memory_summary:{cid} exists: {r.exists(summ_key)}')
    
    # 2. npc_decisions
    dec_key = f'npc_decisions:{cid}'
    dec_entries = r.zrevrange(dec_key, 0, 9, withscores=False)
    print(f'npc_decisions:{cid} count: {len(dec_entries)}')
    
    for i, entry in enumerate(dec_entries[:10]):
        try:
            d = json.loads(entry)
            has_description = bool(d.get('description'))
            has_category = bool(d.get('category'))
            action_taken = d.get('action_taken', 'N/A')
            has_action_desc = bool(d.get('action_desc'))
            target_faction = d.get('target_faction', 'N/A')
            decision_char_id = d.get('char_id', 'N/A')
            
            # Calculate expected score using current logic
            score = 1
            etype = d.get('type', 'decision')
            if etype == 'decision':
                category = d.get('category', 'unknown')
                if category in ('advance_goal', 'investigate', 'seek_resources',
                               'self_improve', 'explore', 'help_ally',
                               'confront_rival', 'socialise', 'socialize'):
                    score += 2
                elif category in ('rest', 'observe', 'unknown'):
                    score += 1
                if d.get('action_taken') or d.get('action_desc'):
                    score += 1
                if d.get('target_faction'):
                    score += 1
            
            if i < 5:
                print(f'  [{i}] char_id={decision_char_id} cat={d.get("category", "N/A")} '
                      f'desc={has_description} action_taken={action_taken} '
                      f'action_desc={has_action_desc} target_faction={target_faction} '
                      f'EXPECTED_SCORE={score}')
                if has_description:
                    print(f'       desc_preview: {d.get("description", "")[:100]}')
        except Exception as e:
            print(f'  [{i}] PARSE ERROR: {e}')
    
    # 3. npc_actions
    act_key = f'npc_actions:{cid}'
    act_entries = r.zrevrange(act_key, 0, 4, withscores=False)
    print(f'npc_actions:{cid} count: {len(act_entries)}')
    for entry in act_entries[:3]:
        try:
            d = json.loads(entry)
            print(f'  action: {str(d.get("action", d.get("type", "N/A")))[:80]} '
                  f'desc={str(d.get("description", ""))[:80]}')
        except:
            print(f'  PARSE ERROR')
    
    # 4. npc_activity (if exists)
    activity_key = f'npc_activity:{cid}'
    act2_entries = r.zrevrange(activity_key, 0, 4, withscores=False) if r.exists(activity_key) else []
    print(f'npc_activity:{cid} count: {len(act2_entries)}')
    for entry in act2_entries[:3]:
        try:
            d = json.loads(entry)
            print(f'  activity: {str(d)[:100]}')
        except:
            print(f'  PARSE ERROR')
    
    # Check any other related keys
    related = []
    for pattern in [f'npc_thoughts:{cid}*', f'npc:{cid}*']:
        related.extend(r.keys(pattern))
    if related:
        print(f'Related keys: {", ".join(related[:5])}')
