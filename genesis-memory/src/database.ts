import initSqlJs, { Database } from 'sql.js';
import fs from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import type { Memory, SearchResult, AddMemoryInput, SearchMemoriesInput, UpdateMemoryInput, ListMemoriesInput, ExportMemoriesInput, GetStatsInput } from './types.js';

const SQL = await initSqlJs();

export class GenesisDatabase {
  private db!: Database;
  private dbPath: string;

  constructor(dbPath: string) {
    this.dbPath = path.resolve(dbPath);
    this.load();
  }

  private load(): void {
    let data: Uint8Array | null = null;
    if (fs.existsSync(this.dbPath)) {
      const raw = fs.readFileSync(this.dbPath);
      if (raw.byteLength > 0) data = new Uint8Array(raw);
    }
    this.db = data ? new SQL.Database(data) : new SQL.Database();
    this.createSchema();
  }

  private persist(): void {
    const data = this.db.export();
    const dir = path.dirname(this.dbPath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(this.dbPath, Buffer.from(data));
  }

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
  }

  private queryAll(sql: string, params: (string | number)[] = []): Record<string, unknown>[] {
    const stmt = this.db.prepare(sql);
    if (params.length > 0) stmt.bind(params);
    const rows: Record<string, unknown>[] = [];
    while (stmt.step()) {
      rows.push(stmt.getAsObject());
    }
    stmt.free();
    return rows;
  }

  private queryOne(sql: string, params: (string | number)[] = []): Record<string, unknown> | null {
    const rows = this.queryAll(sql, params);
    return rows.length > 0 ? rows[0] : null;
  }

  private toMemory(row: Record<string, unknown>): Memory {
    return {
      id: row.id as string,
      content: row.content as string,
      containerTag: row.containerTag as string,
      metadata: JSON.parse((row.metadata as string) || '{}'),
      createdAt: row.createdAt as string,
      updatedAt: row.updatedAt as string,
    };
  }

  init(): void {}

  addMemory(input: AddMemoryInput): Memory {
    const id = input.id || uuidv4();
    const now = new Date().toISOString();
    const stmt = this.db.prepare('INSERT INTO memories (id, content, containerTag, metadata, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)');
    stmt.bind([id, input.content, input.containerTag, JSON.stringify(input.metadata ?? {}), now, now]);
    stmt.step();
    stmt.free();
    this.persist();
    return { id, content: input.content, containerTag: input.containerTag, metadata: input.metadata ?? {}, createdAt: now, updatedAt: now };
  }

  getMemory(id: string): Memory | null {
    const row = this.queryOne('SELECT * FROM memories WHERE id = ?', [id]);
    return row ? this.toMemory(row) : null;
  }

  updateMemory(id: string, input: UpdateMemoryInput): Memory | null {
    const existing = this.getMemory(id);
    if (!existing) return null;
    const content = input.content ?? existing.content;
    const metadata = input.metadata ?? existing.metadata;
    const containerTag = input.containerTag ?? existing.containerTag;
    const now = new Date().toISOString();
    const stmt = this.db.prepare('UPDATE memories SET content = ?, metadata = ?, containerTag = ?, updatedAt = ? WHERE id = ?');
    stmt.bind([content, JSON.stringify(metadata), containerTag, now, id]);
    stmt.step();
    stmt.free();
    this.persist();
    return { id, content, containerTag, metadata, createdAt: existing.createdAt, updatedAt: now };
  }

  deleteMemory(id: string): boolean {
    const existing = this.getMemory(id);
    if (!existing) return false;
    const stmt = this.db.prepare('DELETE FROM memories WHERE id = ?');
    stmt.bind([id]);
    stmt.step();
    stmt.free();
    this.persist();
    return true;
  }

  deleteMemoriesByTag(containerTag: string): void {
    const stmt = this.db.prepare('DELETE FROM memories WHERE containerTag = ?');
    stmt.bind([containerTag]);
    stmt.step();
    stmt.free();
    this.persist();
  }

  searchMemories(input: SearchMemoriesInput): SearchResult[] {
    const tokens = input.query.split(/\s+/).filter(Boolean);
    if (tokens.length === 0) return [];
    const clauses = tokens.map(() => '(content LIKE ? OR metadata LIKE ?)').join(' AND ');
    const sql = `SELECT * FROM memories WHERE containerTag = ? AND ${clauses} ORDER BY createdAt DESC LIMIT ?`;
    const params: (string | number)[] = [input.containerTag];
    for (const t of tokens) params.push(`%${t}%`, `%${t}%`);
    params.push(input.limit ?? 10);
    const rows = this.queryAll(sql, params);
    return rows.map(row => ({ memory: this.toMemory(row) }));
  }

  listMemories(input: ListMemoriesInput): Memory[] {
    const limit = input.limit ?? 20;
    let rows: Record<string, unknown>[];
    if (input.containerTag) {
      rows = this.queryAll('SELECT * FROM memories WHERE containerTag = ? ORDER BY createdAt DESC LIMIT ?', [input.containerTag, limit]);
    } else {
      rows = this.queryAll('SELECT * FROM memories ORDER BY createdAt DESC LIMIT ?', [limit]);
    }
    return rows
      .map(row => this.toMemory(row))
      .filter(mem => !input.before || mem.createdAt < input.before);
  }

  exportMemories(input: ExportMemoriesInput): Memory[] {
    let rows: Record<string, unknown>[];
    if (input.containerTag) {
      rows = this.queryAll('SELECT * FROM memories WHERE containerTag = ? ORDER BY createdAt ASC', [input.containerTag]);
    } else {
      rows = this.queryAll('SELECT * FROM memories ORDER BY createdAt ASC');
    }
    return rows.map(row => this.toMemory(row));
  }

  getStats(input: GetStatsInput): { total: number; tags: number } {
    if (input.containerTag) {
      const row = this.queryOne('SELECT COUNT(*) as total FROM memories WHERE containerTag = ?', [input.containerTag]);
      return { total: (row?.total as number) ?? 0, tags: 1 };
    }
    const row = this.queryOne('SELECT COUNT(*) as total, COUNT(DISTINCT containerTag) as tags FROM memories');
    return { total: (row?.total as number) ?? 0, tags: (row?.tags as number) ?? 0 };
  }

  get allCount(): number {
    return this.getStats({}).total;
  }
}
