"""Explicit schema11 implementation-evidence storage on the original library."""
IMPLEMENTATION_SCHEMA_VERSION = 11
IMPLEMENTATION_TABLES = ('eng_repository_baselines', 'eng_packages')
IMPLEMENTATION_DDL = """
CREATE TABLE eng_repository_baselines (
  realm_id TEXT NOT NULL, project_id TEXT NOT NULL,
  repository_id TEXT NOT NULL, vcs TEXT NOT NULL CHECK(vcs IN ('git','none')),
  commit_key TEXT NOT NULL, tree_digest TEXT NOT NULL,
  overlay_key TEXT NOT NULL,
  ref_bytes BLOB NOT NULL CHECK(typeof(ref_bytes)='blob' AND length(ref_bytes) BETWEEN 1 AND 4096),
  body_digest TEXT NOT NULL CHECK(length(body_digest)=64),
  canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
  CHECK((vcs='none' AND commit_key='') OR
        (vcs='git' AND (commit_key='' OR length(commit_key) IN (40,64)))),
  CHECK(overlay_key='' OR length(overlay_key)=64),
  PRIMARY KEY(realm_id,project_id,repository_id,vcs,commit_key,tree_digest,overlay_key)
);
CREATE TABLE eng_packages (
  realm_id TEXT NOT NULL, project_id TEXT NOT NULL, package_id TEXT NOT NULL,
  digest TEXT NOT NULL CHECK(length(digest)=64),
  canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
  PRIMARY KEY(realm_id,project_id,package_id)
);
CREATE TRIGGER eng_repository_baselines_no_update BEFORE UPDATE ON eng_repository_baselines
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_repository_baselines_no_delete BEFORE DELETE ON eng_repository_baselines
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_packages_no_update BEFORE UPDATE ON eng_packages
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_packages_no_delete BEFORE DELETE ON eng_packages
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
