#!/usr/bin/env python3
"""Snapshot current Git-listed source files without following path ancestors."""
from __future__ import annotations
import hashlib, json, os, shutil, stat, subprocess, sys
from pathlib import Path, PurePosixPath

PRIVATE_ROOTS=("worktree/", ".c1-001-runtime/", ".c1-001-secrets/", ".mimocode/",
               ".qoder/", "runtime/", "verify-logs/", ".baseline-evidence/",
               ".cleanup-evidence/", ".venv-nightly/", ".venv-cleanup/",
               ".venv-decision/", ".decision-tmp/", ".nightly-cache/", ".git/",
               "packaging/.cache/", "packaging/.staging/", "packaging/.out/",
               "packaging/.icon-stage/", "packaging/.keys/")
PRIVATE_EXACT={".env", "token"}
PRIVATE_SUFFIXES=("/.env",)
CACHE_PARTS={"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
             ".npm", ".tox", ".mypy_cache", ".ruff_cache", "coverage",
             "site-packages", ".cache"}

class SnapshotError(RuntimeError):
    pass

def private_path(path: str) -> bool:
    return path.startswith(PRIVATE_ROOTS) or path in PRIVATE_EXACT or path.endswith(PRIVATE_SUFFIXES)

def checked_rel(path: str) -> PurePosixPath:
    p=PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts or "\\" in path or path==".":
        raise SnapshotError(f"unsafe Git path: {path!r}")
    return p

def decode_paths(blob: bytes) -> list[str]:
    result=[]
    for raw in blob.split(b"\0"):
        if raw:
            try: value=raw.decode("utf-8","strict")
            except UnicodeDecodeError as exc: raise SnapshotError("non-UTF8 Git path") from exc
            checked_rel(value); result.append(value)
    return result

def git_bytes(source: Path, *args: str) -> bytes:
    return subprocess.run(["git","-C",str(source),*args],check=True,stdout=subprocess.PIPE).stdout

def git_inventory(source: Path) -> tuple[list[str],list[str]]:
    return (decode_paths(git_bytes(source,"ls-files","--cached","-z")),
            decode_paths(git_bytes(source,"ls-files","--others","--exclude-standard","-z")))

def lstat_without_symlink_ancestors(source: Path, rel: PurePosixPath):
    """Inspect each ancestor with lstat; never traverse an ancestor symlink."""
    current=source
    for index,part in enumerate(rel.parts):
        current=current/part
        try: info=current.lstat()
        except FileNotFoundError: return None
        if index < len(rel.parts)-1 and stat.S_ISLNK(info.st_mode):
            raise SnapshotError(f"symlink path ancestor refused: {current.relative_to(source).as_posix()}")
        if index < len(rel.parts)-1 and not stat.S_ISDIR(info.st_mode):
            raise SnapshotError(f"non-directory path ancestor refused: {current.relative_to(source).as_posix()}")
    return info

def _path_under(path: Path, root: Path) -> Path:
    """Require an existing, non-symlink directory chain below root."""
    root=root.resolve(strict=True)
    candidate=Path(os.path.abspath(path))
    try: rel=candidate.relative_to(root)
    except ValueError as exc: raise SnapshotError(f"output path escapes cache root: {candidate}") from exc
    current=root
    for part in rel.parts[:-1]:
        current=current/part
        try: info=current.lstat()
        except FileNotFoundError as exc: raise SnapshotError(f"output parent missing: {current}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SnapshotError(f"output parent is not a real directory: {current}")
    return candidate

def validate_outputs(source: Path, dest: Path, manifest: Path) -> tuple[Path,Path]:
    cache=source/".nightly-cache"
    try: info=cache.lstat()
    except FileNotFoundError as exc: raise SnapshotError(".nightly-cache missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SnapshotError(".nightly-cache must be a real directory")
    cache_real=cache.resolve(strict=True)
    dest=_path_under(dest,cache_real)
    manifest=_path_under(manifest,cache_real)
    if dest.exists() or dest.is_symlink(): raise SnapshotError("destination already exists")
    if manifest.exists() or manifest.is_symlink(): raise SnapshotError("manifest already exists")
    try: manifest.relative_to(dest)
    except ValueError: pass
    else: raise SnapshotError("manifest must not be inside destination tree")
    return dest,manifest

def _link_target(source: Path, path: str, link: str, listed: set[str], regular_paths: set[str]) -> str:
    if os.path.isabs(link): raise SnapshotError(f"absolute symlink refused: {path}")
    lexical=Path(os.path.normpath(os.path.join(os.path.dirname(path),link))).as_posix()
    try: target_rel=PurePosixPath(lexical).as_posix()
    except Exception as exc: raise SnapshotError(f"invalid symlink target: {path}") from exc
    target_rel=target_rel.removeprefix("./")
    checked_rel(target_rel)
    if private_path(target_rel): raise SnapshotError(f"symlink to private path refused: {path} -> {target_rel}")
    if target_rel not in listed or target_rel not in regular_paths:
        raise SnapshotError(f"symlink target is not a copied regular inventory file: {path} -> {target_rel}")
    # Also validate target ancestors without resolving/following links.
    st=lstat_without_symlink_ancestors(source,checked_rel(target_rel))
    if st is None or not stat.S_ISREG(st.st_mode): raise SnapshotError(f"symlink target unavailable: {path} -> {target_rel}")
    return target_rel

def build_snapshot(source: Path, dest: Path, manifest: Path, tracked: list[str], untracked: list[str], *, read_bytes=None, metadata=None) -> dict:
    source=source.resolve(strict=True)
    if not source.is_dir(): raise SnapshotError("source root is not a directory")
    dest,manifest=validate_outputs(source,dest,manifest)
    tracked_set=set(tracked); all_paths=sorted(tracked_set|set(untracked))
    for path in all_paths: checked_rel(path)
    # Fail before reading any contents if an indexed path occupies known build/cache roots.
    for path in all_paths:
        if private_path(path):
            continue
        parts=checked_rel(path).parts
        if any(part in CACHE_PARTS or part.endswith(".egg-info") for part in parts):
            raise SnapshotError(f"path in generated dependency/cache location: {path}")
    read_bytes=read_bytes or (lambda p:p.read_bytes())
    entries=[]; deleted=[]; excluded=[]; file_data={}
    listed=set(all_paths)
    # First pass is path-only preflight. Private roots are skipped before lstat/content access.
    for path in all_paths:
        if private_path(path):
            excluded.append({"path":path,"reason":"exact known private/environment path; no content read or hash"})
            continue
        rel=checked_rel(path)
        src=source.joinpath(*rel.parts)
        info=lstat_without_symlink_ancestors(source,rel)
        if info is None:
            if path in tracked_set: deleted.append(path)
            continue
        if stat.S_ISLNK(info.st_mode):
            link=os.readlink(src)
            entries.append({"path":path,"kind":"symlink","target":link})
            continue
        if not stat.S_ISREG(info.st_mode): raise SnapshotError(f"non-regular inventory entry refused: {path}")
        data=read_bytes(src)
        digest=hashlib.sha256(data).hexdigest()
        file_data[path]=data
        entries.append({"path":path,"kind":"file","mode":stat.S_IMODE(info.st_mode),"size":len(data),"sha256":digest})
    regular_paths={e["path"] for e in entries if e["kind"]=="file"}
    for entry in entries:
        if entry["kind"]=="symlink":
            _link_target(source,entry["path"],entry["target"],listed,regular_paths)
    # Materialize only after every source path and symlink target passed preflight.
    dest.mkdir(parents=False,exist_ok=False)
    try:
        for entry in entries:
            src=source.joinpath(*checked_rel(entry["path"]).parts)
            target=dest.joinpath(*checked_rel(entry["path"]).parts)
            target.parent.mkdir(parents=True,exist_ok=True)
            if entry["kind"]=="symlink":
                now=lstat_without_symlink_ancestors(source,checked_rel(entry["path"]))
                if now is None or not stat.S_ISLNK(now.st_mode) or os.readlink(src)!=entry["target"]:
                    raise SnapshotError(f"symlink changed during snapshot: {entry['path']}")
                _link_target(source,entry["path"],entry["target"],listed,regular_paths)
                os.symlink(entry["target"],target); continue
            src=source.joinpath(*checked_rel(entry["path"]).parts)
            # Re-check every ancestor and the final file before the second read.
            now=lstat_without_symlink_ancestors(source,checked_rel(entry["path"]))
            if now is None or not stat.S_ISREG(now.st_mode): raise SnapshotError(f"source changed during snapshot: {entry['path']}")
            data=read_bytes(src)
            if hashlib.sha256(data).hexdigest()!=entry["sha256"]: raise SnapshotError(f"source bytes changed during snapshot: {entry['path']}")
            target.write_bytes(data); os.chmod(target,entry["mode"])
    except BaseException:
        shutil.rmtree(dest,ignore_errors=True)
        raise
    tree=hashlib.sha256()
    for e in sorted(entries,key=lambda x:x["path"]): tree.update(e["path"].encode()+b"\0"+e.get("sha256",e.get("target","")).encode()+b"\n")
    payload={"source_root":str(source),"snapshot_root":str(dest),"tracked_paths":len(tracked),
             "untracked_nonignored_paths":len(untracked),"copied_entries":len(entries),
             "copied_bytes":sum(e.get("size",0) for e in entries),"tree_sha256":tree.hexdigest(),
             "deleted_tracked_paths":deleted,"excluded_known_private_paths":excluded,"entries":entries,
             "selection":"read-only Git cached and nonignored-untracked inventory; current working-tree bytes",
             "generic_name_policy":"runtime/build/dist and credential-like basenames are not filtered",
             "git_mutations":False}
    if metadata: payload.update(metadata)
    # Re-validate output ancestry immediately before creating manifest; never follow links.
    manifest=_path_under(manifest,source/".nightly-cache")
    if manifest.exists() or manifest.is_symlink(): raise SnapshotError("manifest appeared during snapshot")
    manifest.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    return payload

def main(argv: list[str]) -> int:
    if len(argv)!=4: raise SystemExit("usage: verify-clean_snapshot.py SOURCE DEST MANIFEST")
    source=Path(argv[1]).resolve(strict=True)
    tracked,untracked=git_inventory(source)
    status=git_bytes(source,"status","--short","--untracked-files=all","-z")
    head=git_bytes(source,"rev-parse","HEAD").decode("ascii").strip()
    payload=build_snapshot(source,Path(argv[2]),Path(argv[3]),tracked,untracked,metadata={"head":head,"git_status_sha256":hashlib.sha256(status).hexdigest()})
    print(f"snapshot entries={payload['copied_entries']} bytes={payload['copied_bytes']} deleted_tracked={len(payload['deleted_tracked_paths'])} tree={payload['tree_sha256']}")
    return 0

if __name__=="__main__": raise SystemExit(main(sys.argv))
