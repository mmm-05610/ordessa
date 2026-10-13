"""Additive schema3; original schema2 tables retain their bytes and identities."""
SNAPSHOT_SCHEMA_VERSION = 3
SNAPSHOT_DDL = """
CREATE TABLE eng_method_blobs (
  digest TEXT PRIMARY KEY,
  byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
  body BLOB NOT NULL CHECK (length(body) = byte_length)
);
CREATE TABLE eng_method_snapshots (
  snapshot_digest TEXT PRIMARY KEY,
  canonical_bytes BLOB NOT NULL
);
CREATE TABLE eng_method_releases (
  method_id TEXT NOT NULL,
  release_version TEXT NOT NULL,
  schema_version INTEGER NOT NULL CHECK (schema_version > 0),
  snapshot_digest TEXT NOT NULL REFERENCES eng_method_snapshots(snapshot_digest),
  PRIMARY KEY (method_id, release_version)
);
CREATE TABLE eng_schema_migrations (
  target_version INTEGER PRIMARY KEY,
  source_digest TEXT NOT NULL,
  backup_sha256 TEXT NOT NULL,
  backup_path TEXT NOT NULL
);
"""
