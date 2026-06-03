export interface Memory {
  id: string;
  content: string;
  containerTag: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface SearchResult {
  memory: Memory;
  snippet?: string;
}

export interface AddMemoryInput {
  content: string;
  containerTag: string;
  metadata?: Record<string, unknown>;
  id?: string;
}

export interface SearchMemoriesInput {
  query: string;
  containerTag: string;
  limit?: number;
}

export interface GetMemoryInput {
  id: string;
}

export interface UpdateMemoryInput {
  id: string;
  content?: string;
  metadata?: Record<string, unknown>;
  containerTag?: string;
}

export interface DeleteMemoryInput {
  id: string;
}

export interface DeleteMemoriesByTagInput {
  containerTag: string;
}

export interface ListMemoriesInput {
  containerTag?: string;
  limit?: number;
  before?: string;
}

export interface ExportMemoriesInput {
  containerTag?: string;
}

export interface GetStatsInput {
  containerTag?: string;
}
