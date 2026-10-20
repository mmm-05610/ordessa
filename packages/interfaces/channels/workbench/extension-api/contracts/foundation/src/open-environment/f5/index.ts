/**
 * Public entry of the frozen F5 contract (T008-11 incremental freeze).
 *
 * One module source, consumed later through the shared carrier. Types only:
 * implementations (T008-12..20) must satisfy these signatures exactly and
 * keep the F5 §8 ruling — self-built minimal mechanisms on the existing
 * useSyncExternalStore/ServiceCore foundations, no new runtime dependencies.
 */
export * from './absence'
export * from './errors'
export * from './tokens'
export * from './types'
