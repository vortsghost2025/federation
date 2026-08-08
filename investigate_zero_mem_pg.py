import json
import os
import psycopg2
import psycopg2.extras

focus = ['comp_007', 'comp_006', 'comp_009', 'char_204', 'char_303', 'char_401', 'char_001']

db_url = os.environ.get('DATABASE_URL', 'postgresql://federation:federation@postgres:5432/federation')
conn = psycopg2.connect(db_url)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print('=' * 70)
print('POSTGRES npc_action_logs INVESTIGATION')
print('=' * 70)

cur.execute("""
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'npc_action_logs'
    ORDER BY ordinal_position
""")
print('columns:', ', '.join(row['column_name'] for row in cur.fetchall()))

for cid in focus:
    print('\n' + '=' * 50)
    print(f'NPC: {cid}')
    print('=' * 50)

    cur.execute("""
        SELECT entry_type, COUNT(*) AS count
        FROM npc_action_logs
        WHERE char_id = %s
          AND created_at >= NOW() - INTERVAL '24 hours'
        GROUP BY entry_type
        ORDER BY count DESC, entry_type
    """, (cid,))
    rows = cur.fetchall()
    print('24h counts by entry_type:')
    if rows:
        for row in rows:
            print(f"  {row['entry_type']}: {row['count']}")
    else:
        print('  none')

    cur.execute("""
        SELECT id, char_id, entry_type, data_json, timestamp, created_at
        FROM npc_action_logs
        WHERE char_id = %s
        ORDER BY created_at DESC
        LIMIT 5
    """, (cid,))
    rows = cur.fetchall()
    print('latest 5 rows:')
    if not rows:
        print('  none')
    for row in rows:
        data = row.get('data_json') or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {'raw': data}
        summary = {
            'category': data.get('category'),
            'description': (data.get('description') or '')[:120],
            'action_taken': data.get('action_taken'),
            'action_desc': (data.get('action_desc') or '')[:120],
            'reasoning': (data.get('reasoning') or '')[:120],
        }
        print(f"  id={row['id']} type={row['entry_type']} ts={row['timestamp']} created={row['created_at']} data={summary}")

cur.close()
conn.close()
