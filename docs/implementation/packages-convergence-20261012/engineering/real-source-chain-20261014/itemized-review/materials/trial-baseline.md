# TRIAL DID: explicit local source mapping, baseline v1

This is a caller-authored engineering test design, not an Ordessa product DID,
production project configuration, permission grant, or historical code receipt.

Scope: realm `local-source-chain-test`, project `caller-authored-project`.
Logical source document: `project-files` / `itemized-source-mapping-DID`.
This baseline's upstream version is `itemized-baseline-v1`. The review supplies its
full SourceRef, digest and byte length out of band; the caller retains its bytes
in the explicit file `trial-baseline.md`. A digest alone cannot recover content.

## Goal and baseline rule

The local host may read only a finite set of caller-selected source versions
while Engineering records their exact references on its original owners. A
logical document identity is currently used as the relative file path. The
host supplies the exact scope, an absolute project root and complete SourceRefs.
The reader checks the selected reference, file length and content digest. It
does not select a latest version, scan directories, write source documents or
create an archive.

For this trial baseline, one mutable file holds one document's currently
retained bytes. Two versions with the same locator therefore resolve to the
same path. If version v1 and v2 have different bytes, that one file cannot supply
both exact captures at the same time. A mismatch must be refused, never disguised
as a historical version. The caller must not overwrite a previously pinned
version to make a different reference succeed.

## Required change and constraints

Separate logical source identity from an explicitly supplied relative path so
the caller can retain v1 and v2 in two different files. Preserve complete ref
checking, length/digest checks, scoped finite selection and read-only behavior.
Do not infer paths or versions, create fallback chains, expand read authority,
change public SourceRef or SourceMaterialPort, scan Git/projects, or add a second
Engineering record owner.

This design concerns only local bounded source reads. It does not provide a
historical immutable archive or default Product authentication. It does not
approve any change, execute a method, produce a human Grant or dispatch work.
Review, association and Package recording retain their original separate gates.

Acceptance must demonstrate two versions of one logical document read from two
explicit files, and refusals for changed refs, content, unavailable files and
scope. Source-level controlled tests can support those mechanism claims; they
cannot establish production authorization or model review quality.
