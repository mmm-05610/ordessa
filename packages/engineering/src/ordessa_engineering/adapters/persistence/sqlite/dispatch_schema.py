"""Explicit schema13 columns for dispatch state on the original step_log."""

DISPATCH_SCHEMA_VERSION = 13

DISPATCH_DDL = """
ALTER TABLE step_log ADD COLUMN dispatch_scope_json TEXT;
ALTER TABLE step_log ADD COLUMN binding_digest TEXT;
ALTER TABLE step_log ADD COLUMN binding_bytes BLOB;
ALTER TABLE step_log ADD COLUMN execution_operation_ref TEXT;
ALTER TABLE step_log ADD COLUMN dispatch_phase TEXT
 CHECK(dispatch_phase IS NULL OR dispatch_phase IN
       ('reserved','possibly_written','completed','failed','unknown'));
ALTER TABLE step_log ADD COLUMN dispatch_version INTEGER NOT NULL DEFAULT 0
 CHECK(typeof(dispatch_version)='integer' AND dispatch_version BETWEEN 0 AND 9007199254740991);
ALTER TABLE step_log ADD COLUMN dispatch_fence INTEGER NOT NULL DEFAULT 1
 CHECK(typeof(dispatch_fence)='integer' AND dispatch_fence BETWEEN 1 AND 9007199254740991);
ALTER TABLE step_log ADD COLUMN result_blob_json TEXT;

CREATE UNIQUE INDEX step_log_dispatch_attempt_unique
 ON step_log(run_id,step_id,attempt) WHERE binding_digest IS NOT NULL;
CREATE UNIQUE INDEX step_log_execution_operation_unique
 ON step_log(execution_operation_ref) WHERE execution_operation_ref IS NOT NULL;

CREATE TRIGGER step_log_dispatch_insert_valid BEFORE INSERT ON step_log
WHEN NEW.binding_digest IS NOT NULL AND (
 NEW.dispatch_scope_json IS NULL OR NEW.binding_bytes IS NULL
 OR NEW.execution_operation_ref IS NULL OR NEW.dispatch_phase IS NOT 'reserved'
 OR NEW.status!='reserved' OR NEW.dispatch_version!=0 OR NEW.dispatch_fence!=1
 OR NEW.result_blob_json IS NOT NULL OR NEW.operation!='engineering.execution.dispatch'
 OR typeof(NEW.dispatch_scope_json)!='text' OR typeof(NEW.binding_digest)!='text'
 OR length(NEW.binding_digest)!=64 OR typeof(NEW.binding_bytes)!='blob'
 OR length(NEW.binding_bytes) NOT BETWEEN 1 AND 2097152
 OR typeof(NEW.execution_operation_ref)!='text'
)
BEGIN SELECT RAISE(ABORT, 'DISPATCH_BINDING_INVALID'); END;

CREATE TRIGGER step_log_dispatch_binding_immutable BEFORE UPDATE ON step_log
WHEN OLD.binding_digest IS NOT NULL AND (
 NEW.run_id IS NOT OLD.run_id OR NEW.step_id IS NOT OLD.step_id OR NEW.attempt IS NOT OLD.attempt
 OR NEW.ordinal IS NOT OLD.ordinal OR NEW.operation IS NOT OLD.operation
 OR NEW.dispatch_scope_json IS NOT OLD.dispatch_scope_json
 OR NEW.binding_digest IS NOT OLD.binding_digest OR NEW.binding_bytes IS NOT OLD.binding_bytes
 OR NEW.execution_operation_ref IS NOT OLD.execution_operation_ref
 OR NEW.dispatch_fence IS NOT OLD.dispatch_fence
 OR NEW.receipt_ref_json IS NOT OLD.receipt_ref_json
)
BEGIN SELECT RAISE(ABORT, 'DISPATCH_BINDING_IMMUTABLE'); END;

CREATE TRIGGER step_log_dispatch_transition BEFORE UPDATE ON step_log
WHEN OLD.binding_digest IS NOT NULL AND (
 NEW.dispatch_version IS NOT OLD.dispatch_version+1
 OR NEW.dispatch_phase IS NULL OR NOT (
   (OLD.dispatch_phase='reserved' AND NEW.dispatch_phase='possibly_written')
   OR (OLD.dispatch_phase IN ('possibly_written','unknown')
       AND NEW.dispatch_phase IN ('completed','failed','unknown'))
 )
 OR NEW.status IS NOT NEW.dispatch_phase
)
BEGIN SELECT RAISE(ABORT, 'DISPATCH_TRANSITION_INVALID'); END;

CREATE TRIGGER step_log_dispatch_terminal_immutable BEFORE UPDATE ON step_log
WHEN OLD.binding_digest IS NOT NULL AND OLD.dispatch_phase IN ('completed','failed')
BEGIN SELECT RAISE(ABORT, 'DISPATCH_TERMINAL_IMMUTABLE'); END;

CREATE TRIGGER step_log_dispatch_bound_no_delete BEFORE DELETE ON step_log
WHEN OLD.binding_digest IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'DISPATCH_BINDING_IMMUTABLE'); END;
"""

DISPATCH_TABLES = ('step_log',)
