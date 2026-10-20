-- Persist the full evidence ArtifactRef metadata for ResourceObservations.
--
-- 007 stored only the evidence locator (type/provider/native_id/uri), so a
-- round-trip rebuilt every evidence_ref with empty metadata.  This column
-- keeps the normalized metadata JSON beside the locator; rows written under
-- 007 read back with '{}' (their metadata was never recorded and is not
-- fabricated here).

BEGIN IMMEDIATE;

ALTER TABLE core_resource_observations
    ADD COLUMN evidence_meta_json TEXT NOT NULL DEFAULT '{}';

COMMIT;
