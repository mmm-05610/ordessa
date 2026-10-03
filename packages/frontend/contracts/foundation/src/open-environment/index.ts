/**
 * Public entry of the frozen open-environment TS contract mirror.
 * One module source for the shared carrier rule: every consumer imports the
 * contract from this module (or its built contract artifact), never from a
 * copy — a second copy of these types is the C95-2 "两份 Token" counterexample
 * at the type level.
 */
export * from './codec'
export * from './types'
