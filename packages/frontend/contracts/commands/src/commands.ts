import { Token, type ResourceScope, type IDisposable } from '@ordessa/extension-api'
export interface Observable<T> { getSnapshot(): readonly T[]; subscribe(listener: () => void): () => void }
export interface Command { id: string; title: string; execute(): unknown | Promise<unknown> }
export type CommandResult = { ok: true; value: unknown } | { ok: false; error: string }
export interface Commands extends Observable<Pick<Command, 'id' | 'title'>> {
  forScope(scope: ResourceScope): { add(command: Command): IDisposable }
  execute(id: string): Promise<CommandResult>
}
export const CommandsToken = new Token<Commands>('ordessa.commands.v1')
