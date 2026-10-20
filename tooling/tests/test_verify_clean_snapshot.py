"""Controlled filesystem counters for verify-clean snapshot path safety.

These tests monkeypatch only the Git inventory selector; they are not evidence
that the real checkout inventory or a complete snapshot has been validated.
"""
from __future__ import annotations
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

HELPER=Path(__file__).parents[1]/"checks"/"verify-clean_snapshot.py"
spec=importlib.util.spec_from_file_location("verify_clean_snapshot_candidate",HELPER)
assert spec and spec.loader
snapshot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)

class SnapshotCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/"repo"
        self.cache=self.root/".nightly-cache"
        self.cache.mkdir(parents=True)
        self.run=self.cache/"run"
        self.run.mkdir()
        self.dest=self.run/"source"
        self.manifest=self.run/"manifest.json"

    def tearDown(self): self.temp.cleanup()

    def put(self,rel,data=b"source"):
        path=self.root/rel; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data); return path

    def build(self,tracked,untracked=(),**kwargs):
        return snapshot.build_snapshot(self.root,self.dest,self.manifest,list(tracked),list(untracked),**kwargs)

    def test_generic_owner_names_are_preserved(self):
        paths=["packages/interfaces/cli/runtime/entry.py","tooling/build/driver.py","plugins/provider/dist/source.mjs","credentials_adapter.py"]
        for path in paths: self.put(path,path.encode())
        self.build(paths)
        for path in paths: self.assertEqual((self.dest/path).read_bytes(),path.encode())

    def test_deleted_tracked_is_recorded_without_restoring_head(self):
        self.build(["src/deleted.py"])
        self.assertEqual(json_read(self.manifest)["deleted_tracked_paths"],["src/deleted.py"])
        self.assertFalse((self.dest/"src/deleted.py").exists())

    def test_nonignored_untracked_source_is_included(self):
        self.put("new/source.py",b"new")
        self.build([], ["new/source.py"])
        self.assertEqual((self.dest/"new/source.py").read_bytes(),b"new")

    def test_exact_private_path_is_not_read_or_hashed(self):
        self.put(".c1-001-secrets/token",b"private")
        self.put("src/public.py",b"public")
        def guarded(path):
            if ".c1-001-secrets" in path.parts: raise AssertionError("private bytes opened")
            return path.read_bytes()
        self.build([".c1-001-secrets/token","src/public.py"],read_bytes=guarded)
        manifest=json_read(self.manifest)
        self.assertEqual(manifest["excluded_known_private_paths"][0]["path"],".c1-001-secrets/token")
        self.assertNotIn("sha256",str(manifest["excluded_known_private_paths"]))
        self.assertFalse((self.dest/".c1-001-secrets/token").exists())

    def test_external_file_symlink_is_refused(self):
        outside=Path(self.temp.name)/"outside.py"; outside.write_bytes(b"outside")
        (self.root/"src").mkdir(); (self.root/"src/link.py").symlink_to(outside)
        with self.assertRaises(snapshot.SnapshotError): self.build(["src/link.py"])
        self.assertFalse(self.dest.exists())

    def test_symlink_in_ancestor_is_refused_before_read(self):
        outside=Path(self.temp.name)/"external"; outside.mkdir(); (outside/"secret.py").write_bytes(b"outside")
        (self.root/"linked").symlink_to(outside,target_is_directory=True)
        with self.assertRaises(snapshot.SnapshotError): self.build(["linked/secret.py"])
        self.assertFalse(self.dest.exists())

    def test_internal_symlink_to_private_target_is_refused(self):
        self.put(".c1-001-secrets/private.py",b"secret")
        (self.root/"src").mkdir(); (self.root/"src/ref.py").symlink_to("../.c1-001-secrets/private.py")
        with self.assertRaises(snapshot.SnapshotError):
            self.build(["src/ref.py",".c1-001-secrets/private.py"])
        self.assertFalse(self.dest.exists())

    def test_manifest_outside_nightly_cache_is_refused(self):
        outside=Path(self.temp.name)/"manifest.json"
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.build_snapshot(self.root,self.dest,outside,["source.py"],[])
        self.assertFalse(self.dest.exists())

    def test_existing_destination_is_refused_without_overwrite(self):
        self.dest.mkdir(); marker=self.dest/"keep"; marker.write_text("existing")
        with self.assertRaises(snapshot.SnapshotError): self.build(["src.py"])
        self.assertEqual(marker.read_text(),"existing")

    def test_manifest_inside_snapshot_destination_is_refused(self):
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.build_snapshot(self.root,self.dest,self.dest/"manifest.json",[],[])
        self.assertFalse(self.dest.exists())

    def test_source_change_between_hash_and_copy_is_refused(self):
        path=self.put("src/change.py",b"before"); reads=0
        def changes_after_first_read(file):
            nonlocal reads
            data=file.read_bytes(); reads+=1
            if reads==1: path.write_bytes(b"after")
            return data
        with self.assertRaises(snapshot.SnapshotError):
            self.build(["src/change.py"],read_bytes=changes_after_first_read)
        self.assertFalse(self.dest.exists())


    def test_valid_internal_listed_symlink_is_preserved(self):
        self.put("src/target.py",b"target")
        (self.root/"src/link.py").symlink_to("target.py")
        self.build(["src/link.py","src/target.py"])
        copied=self.dest/"src/link.py"
        self.assertTrue(copied.is_symlink())
        self.assertEqual(os.readlink(copied),"target.py")
        self.assertEqual((self.dest/"src/target.py").read_bytes(),b"target")

    def test_internal_symlink_to_unlisted_target_is_refused(self):
        self.put("src/target.py",b"target")
        self.put("src/other.py",b"other")
        (self.root/"src/link.py").symlink_to("other.py")
        with self.assertRaises(snapshot.SnapshotError): self.build(["src/link.py","src/target.py"])
        self.assertFalse(self.dest.exists())

    def test_private_nested_cache_is_excluded_before_cache_check_or_read(self):
        self.put(".venv-nightly/lib/site-packages/private.py",b"private")
        def forbidden(_path): raise AssertionError("private nested cache content opened")
        self.build([".venv-nightly/lib/site-packages/private.py"],read_bytes=forbidden)
        manifest=json_read(self.manifest)
        self.assertEqual(manifest["excluded_known_private_paths"][0]["path"],".venv-nightly/lib/site-packages/private.py")
        self.assertEqual(manifest["copied_entries"],0)

    def test_cache_root_cannot_be_used_as_existing_destination(self):
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.build_snapshot(self.root,self.cache,self.manifest,[],[])
        self.assertTrue(self.cache.is_dir())
        self.assertFalse(self.manifest.exists())


    def test_destination_outside_nightly_cache_is_refused(self):
        outside=Path(self.temp.name)/"outside-snapshot"
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.build_snapshot(self.root,outside,self.manifest,[],[])
        self.assertFalse(outside.exists())

    def test_manifest_equal_to_destination_is_refused(self):
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.build_snapshot(self.root,self.dest,self.dest,[],[])
        self.assertFalse(self.dest.exists())

    def test_output_symlink_ancestor_is_refused(self):
        outside=Path(self.temp.name)/"outside"; outside.mkdir()
        (self.cache/"linked").symlink_to(outside,target_is_directory=True)
        target=self.cache/"linked"/"snapshot"
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.build_snapshot(self.root,target,self.manifest,[],[])
        self.assertFalse((outside/"snapshot").exists())

    def test_tracked_cache_path_fails_before_content_read(self):
        self.put("src/node_modules/pkg/index.js",b"generated")
        def forbidden(_path): raise AssertionError("cache content opened")
        with self.assertRaises(snapshot.SnapshotError):
            self.build(["src/node_modules/pkg/index.js"],read_bytes=forbidden)
        self.assertFalse(self.dest.exists())

def json_read(path):
    import json
    return json.loads(path.read_text(encoding="utf-8"))

if __name__=="__main__": unittest.main()
