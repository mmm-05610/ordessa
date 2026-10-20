/** View projections supplied by an authoritative owner; never local business state. */
export interface WorkRecord {
  id: string; version: string; scope: string; title: string;
  phase: 'pending' | 'active' | 'result'; status: string; change: string;
  method?: { name: string; steps: readonly { id: string; label: string; status: string }[] };
  basis: readonly string[]; review: readonly string[]; approval: readonly string[];
  execution: readonly string[]; evidence: readonly string[];
}
export interface StructureRecord {
  id: string; title: string; parentId?: string; workIds: readonly string[];
  design: string; implementation: string; acceptance: string;
}
export interface BoardSnapshot {
  revision: string; scope: string; works: readonly WorkRecord[]; structure: readonly StructureRecord[];
}
export interface BoardSource {
  read(): Promise<BoardSnapshot>;
  /** Must atomically compare version/scope at the authority and refuse stale requests. */
  confirm?(request: { id: string; version: string; scope: string; snapshotRevision: string }): Promise<void>;
}
