# FTS5 Migration Plan for genesis-memory

> **Status: STAGED** — waiting for compaction agent Phase 2 to apply to `database.ts`

## Problem

`sql.js` v1.10.3 WASM does NOT include FTS5. Current `searchMemories()` uses
`LIKE '%term%'` which gives:
- No relevance ranking (ordered by `createdAt` only)
- No stemming/tokenization
- No snippet highlighting (`SearchResult.snippet` field is never populated)
- Full table scan on every search
- `metadata LIKE` is fragile (searches raw JSON strings)

## Step 1: Build sql.js with FTS5

```bash
git clone https://github.com/nicolo-ribaudo/sql.js.git
cd sql.js
# Edit Makefile or sqlite.amalgamation/Makefile:
#   Add -DSQLITE_ENABLE_FTS5 to CFLAGS
make
# Copy outputs into genesis-memory:
cp dist/sql-wasm.js  S:/federation/genesis-memory/node_modules/sql.js/dist/
cp dist/sql-wasm.wasm S:/federation/genesis-memory/node_modules/sql.js/dist/
```

Alternative: download a pre-built FTS5-enabled sql.js from
https://github.com/nicolo-ribaudo/sql.js/releases (if available) or build
from sqlite3 amalgamation with `-DSQLITE_ENABLE_FTS5`.

## Step 2: Update createSchema() in database.ts

Replace the current `createSchema()` with:

```ts
private createSchema(): void {
  this.db.run(`
    CREATE TABLE IF NOT EXISTS memories (
      id TEXT PRIMARY KEY,
      content TEXT NOT NULL,
      containerTag TEXT NOT NULL,
      metadata TEXT,
      createdAt TEXT NOT NULL,
      updatedAt TEXT NOT NULL
    )
  `);

  // FTS5 virtual table (content=memories for external content mode)
  this.db.run(`
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(content, metadata, containerTag, content=memories, content_rowid=rowid)
  `);

  // Keep FTS index in sync via triggers
  this.db.run(`
    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
      INSERT INTO memories_fts(rowid, content, metadata, containerTag)
      VALUES (new.rowid, new.content, new.metadata, new.containerTag);
    END
  `);

  this.db.run(`
    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
      INSERT INTO memories_fts(memories_fts, rowid, content, metadata, containerTag)
      VALUES ('delete', old.rowid, old.content, old.metadata, old.containerTag);
    END
  `);

  this.db.run(`
    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
      INSERT INTO memories_fts(memories_fts, rowid, content, metadata, containerTag)
      VALUES ('delete', old.rowid, old.content, old.metadata, old.containerTag);
      INSERT INTO memories_fts(rowid, content, metadata, containerTag)
      VALUES (new.rowid, new.content, new.metadata, new.containerTag);
    END
  `);
}
```

## Step 3: Rewrite searchMemories() in database.ts

Replace the current LIKE-based search with:

```ts
searchMemories(input: SearchMemoriesInput): SearchResult[] {
  const sql = `
    SELECT m.*,
      snippet(memories_fts, 0, '⟨', '⟩', '...', 20) as snippet
    FROM memories_fts
    JOIN memories m ON m.rowid = memories_fts.rowid
    WHERE memories_fts MATCH ?
      AND m.containerTag = ?
    ORDER BY rank
    LIMIT ?
  `;
  const rows = this.queryAll(sql, [input.query, input.containerTag, input.limit ?? 10]);
  return rows.map(row => ({
    memory: this.toMemory(row),
    snippet: row.snippet as string | undefined,
  }));
}
```

This gives:
- ✅ Relevance ranking via FTS5 `rank`
- ✅ Snippet highlighting via `snippet()` (populates `SearchResult.snippet`)
- ✅ Proper tokenization and stemming
- ✅ Inverted index (no full table scan)
- ✅ External content mode (no data duplication)

## Step 4: Update smoke-test.mjs

Add a test case for FTS5 search ranking:

```js
// 17. searchMemories FTS5 (multi-term, ranked)
const fts5Id = callTool('searchMemories', {
  query: 'deployed infrastructure',
  containerTag: 'genesis-kernel',
});
await wait(500);
```

And in the test expectations:

```js
{ id: fts5Id, name: 'searchMemories FTS5 ranked', expect: (r) =>
  r.result?.content?.[0]?.text?.includes('Phase 1') },
```

## Compatibility Note

If FTS5 is NOT available (e.g., fallback to standard sql.js), the triggers
will fail silently at `createSchema()`. Wrap each `this.db.run()` for the
FTS virtual table and triggers in a try/catch to gracefully degrade:

```ts
private createSchema(): void {
  this.db.run(`CREATE TABLE IF NOT EXISTS memories (...)`);
  try {
    this.db.run(`CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts ...`);
    // ... triggers ...
    this.fts5 = true;
  } catch {
    this.fts5 = false;
  }
}
```

Then in `searchMemories()`:

```ts
searchMemories(input: SearchMemoriesInput): SearchResult[] {
  if (this.fts5) {
    // FTS5 MATCH query with ranking and snippets
  } else {
    // Fallback to LIKE queries (current implementation)
  }
}
```

Add `private fts5 = false;` field to the class.
