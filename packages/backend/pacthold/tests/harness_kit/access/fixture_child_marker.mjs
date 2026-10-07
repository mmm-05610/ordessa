/**
 * The argv marker a fixture child carries, shared by the process that starts the child and the
 * tests that look for it in the process table.
 *
 * It has to be in the command line rather than only in a record file because the fact under test is
 * "is this process still running after the release said it was not" — a process that was killed while
 * it was still booting never got to write anything, so a cleanup asserted from the fixture's own
 * account would silently pass on exactly the case that matters.
 */
export const FIXTURE_CHILD_MARKER = "agentbox-fixture-child"
