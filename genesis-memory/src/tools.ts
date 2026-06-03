import { z } from 'zod';
import { GenesisDatabase } from './database.js';
import type { Memory } from './types.js';

export function buildTools(db: GenesisDatabase) {
  return [
    {
      name: 'addMemory',
      description: 'Store a new memory in the local SQLite store. Upserted by id if provided.',
      inputSchema: {
        type: 'object',
        properties: {
          content: { type: 'string', description: 'The memory content to store' },
          containerTag: { type: 'string', description: 'Scope tag (e.g. genesis-kernel, infra, genesis-refactor)' },
          metadata: { type: 'object', description: 'Flexible metadata as a JSON object' },
          id: { type: 'string', description: 'Optional id for idempotent upsert' },
        },
        required: ['content', 'containerTag'],
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { content, containerTag, metadata, id } = z.object({
          content: z.string().min(1),
          containerTag: z.string().min(1),
          metadata: z.record(z.unknown()).optional(),
          id: z.string().uuid().optional(),
        }).parse(args);
        const memory = db.addMemory({ content, containerTag, metadata, id });
        return { ok: true, memory: toPublic(memory) };
      },
    },
    {
      name: 'searchMemories',
      description: 'Full-text search across memory content and metadata, scoped to a containerTag.',
      inputSchema: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'Search string (all terms must match content or metadata)' },
          containerTag: { type: 'string', description: 'Scope tag to search within' },
          limit: { type: 'integer', description: 'Max results (default 10, max 100)' },
        },
        required: ['query', 'containerTag'],
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { query, containerTag, limit } = z.object({
          query: z.string().min(1),
          containerTag: z.string().min(1),
          limit: z.number().int().positive().max(100).optional(),
        }).parse(args);
        const memories = db.searchMemories({ query, containerTag, limit: limit ?? 10 });
        return { ok: true, results: memories.map(r => toPublic(r.memory)) };
      },
    },
    {
      name: 'getMemory',
      description: 'Retrieve a single memory by its id.',
      inputSchema: {
        type: 'object',
        properties: { id: { type: 'string', description: 'Memory UUID' } },
        required: ['id'],
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { id } = z.object({ id: z.string().uuid() }).parse(args);
        const memory = db.getMemory(id);
        if (!memory) return { ok: false, error: 'Memory not found' };
        return { ok: true, memory: toPublic(memory) };
      },
    },
    {
      name: 'updateMemory',
      description: 'Partial update of an existing memory (content, metadata, or containerTag).',
      inputSchema: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          content: { type: 'string' },
          metadata: { type: 'object' },
          containerTag: { type: 'string' },
        },
        required: ['id'],
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { id, content, metadata, containerTag } = z.object({
          id: z.string().uuid(),
          content: z.string().optional(),
          metadata: z.record(z.unknown()).optional(),
          containerTag: z.string().optional(),
        }).parse(args);
        const memory = db.updateMemory(id, { content, metadata, containerTag });
        if (!memory) return { ok: false, error: 'Memory not found' };
        return { ok: true, memory: toPublic(memory) };
      },
    },
    {
      name: 'deleteMemory',
      description: 'Delete a single memory by id.',
      inputSchema: {
        type: 'object',
        properties: { id: { type: 'string' } },
        required: ['id'],
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { id } = z.object({ id: z.string().uuid() }).parse(args);
        const deleted = db.deleteMemory(id);
        return { ok: deleted, deleted };
      },
    },
    {
      name: 'deleteMemoriesByTag',
      description: 'Bulk-delete all memories with a given containerTag.',
      inputSchema: {
        type: 'object',
        properties: { containerTag: { type: 'string' } },
        required: ['containerTag'],
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { containerTag } = z.object({ containerTag: z.string().min(1) }).parse(args);
        db.deleteMemoriesByTag(containerTag);
        return { ok: true };
      },
    },
    {
      name: 'listMemories',
      description: 'Paginated list of memories, optionally filtered by containerTag.',
      inputSchema: {
        type: 'object',
        properties: {
          containerTag: { type: 'string' },
          limit: { type: 'integer', maximum: 100 },
          before: { type: 'string', description: 'ISO timestamp pagination anchor' },
        },
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { containerTag, limit, before } = z.object({
          containerTag: z.string().optional(),
          limit: z.number().int().positive().max(100).optional(),
          before: z.string().optional(),
        }).parse(args);
        const memories = db.listMemories({ containerTag, limit: limit ?? 20, before });
        return { ok: true, memories: memories.map(toPublic) };
      },
    },
    {
      name: 'exportMemories',
      description: 'Full JSON export of memories. Optionally filter by containerTag.',
      inputSchema: {
        type: 'object',
        properties: { containerTag: { type: 'string' } },
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { containerTag } = z.object({ containerTag: z.string().optional() }).parse(args);
        const memories = db.exportMemories({ containerTag });
        return { ok: true, memories: memories.map(toPublic) };
      },
    },
    {
      name: 'getStats',
      description: 'Return aggregate stats: total memory count and tag count.',
      inputSchema: {
        type: 'object',
        properties: { containerTag: { type: 'string' } },
        additionalProperties: false,
      },
      handler: async (args: unknown) => {
        const { containerTag } = z.object({ containerTag: z.string().optional() }).parse(args);
        const stats = db.getStats({ containerTag });
        return {
          ok: true,
          stats: {
            total: stats.total,
            tags: stats.tags,
          },
        };
      },
    },
  ];
}

function toPublic(m: Memory) {
  return {
    id: m.id,
    content: m.content,
    containerTag: m.containerTag,
    metadata: m.metadata,
    createdAt: m.createdAt,
    updatedAt: m.updatedAt,
  };
}
