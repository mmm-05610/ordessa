export interface BoardHost {
  collapse(collapsed: boolean): Promise<void>;
  pin(pinned: boolean): Promise<void>;
  close(): Promise<void>;
}

export interface HostFault { reason: string; remedy: string }
