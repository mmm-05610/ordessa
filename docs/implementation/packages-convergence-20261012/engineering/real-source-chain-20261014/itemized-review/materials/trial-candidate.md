# TRIAL DID: explicit local source mapping, candidate v2

This is the successor to the supplied trial baseline, not a product DID or a
claim that the default Ordessa Product is ready. Scope remains realm
`local-source-chain-test`, project `caller-authored-project`; the logical source
is `project-files` / `itemized-source-mapping-DID`. This candidate's upstream
version is `itemized-candidate-v2` and its retained file is `trial-candidate.md`.
Its full SourceRef and the baseline's separate full SourceRef are supplied with
the invocation. No example identity from another case governs this review.

## One small change

Use `ProjectSourceMaterials(factory, scope, root, source_mappings)` for the local
read port. Each mapping is a complete SourceRef plus an explicit safe relative
file path. Retain the baseline rule that the host selects only a finite set of
refs in one scope, and that the source port is read-only. Replace only the
baseline's document-ID-to-file-path inference. Two versions of one document now
have two explicit paths, so the caller can preserve both captures without
overwriting either. There is no automatic source registration or copying by the
source port; the caller authors and retains the files.

## Claims, evidence and limits

The evidence below is supplied explicitly as facts with exact source/test
identities. The reviewer is not asked to scan a repository or infer behavior
from directory existence. These are source/controlled mechanism checks.

**C1: distinct versions can be read exactly.** The adapter selects a mapping by
full SourceRef equality, then opens only its configured path under a pinned
read-only directory descriptor. It verifies file type, byte length and SHA-256,
and detects changes during the read. The caller may map one locator's v1 to
`archive/v1.md` and v2 to `current.md`; each read must return that version's
captured bytes. Evidence: `test_same_document_versions_require_distinct_explicit_files`
in `packages/engineering/tests/adapters/test_project_sources.py` writes distinct
old/new contents, asserts both exact reads, then asserts v3 refusal. This test
passed in `three-seams-frozen.json` (55 scoped cases, exit0, no skips).

**C2: explicit mappings do not weaken reference or scope checks.** Same locator
and upstream version cannot identify conflicting digest/length. Different
versions of one locator cannot share one mutable path. The reader accepts only
the configured complete ref in the configured scope. Evidence: constructor
checks in `adapters/filesystem/project_sources.py`; parameterized tests alter
digest, length, media type, capturing actor/time, original URL and locator and
assert refusal. Separate cases cover unknown source/version and foreign scope.
Those assertions are part of the same successful 55-case receipt.

**C3: unavailable or changed content refuses without fallback.** A mapped file
missing at read time produces SOURCE_UNAVAILABLE; same-length changed bytes
produce SOURCE_CONTENT_MISMATCH. Intermediate/final symlinks are refused. No
latest-version lookup, directory scan, mtime version inference, write or old
reader fallback is invoked. Evidence: `test_configured_but_missing_file_is_unavailable`,
`test_changed_local_bytes_are_content_mismatch_not_a_new_version`, and symlink
cases in the same test file. The application independently verifies returned
length/digest in `application/usecases/material_closure.py:verify_external_source`.

**C4: record authority remains the original Engineering chain.** Composition
passes this source port with the original factory into the existing
EngineeringPorts/EngineeringService. Source refs are recorded in the original
Change/Proposal, Review and Package owners; no Artifact mirror, second journal
or run store is created. The controlled Service regression creates and reviews
exact sources, associates the review, freezes explicit spec/plan/tasks refs,
and reconnects the original SQLite library to read/replay the same references.
Evidence: `final-service-chain.json` (9 scoped cases, exit0, no skips). Those
cases use the earlier 2.7.0 declaration and `example-DID` captures: they support
the existing mechanism, not an already completed review of this trial pair or
the new 2.7.1 declaration. New-pair checks are separately required before the
live invocation. These checks do not authenticate a production caller/reviewer. A prepared Package
has `dispatchable=false`; missing execution envelope still refuses dispatch.

Exact source identities used for these evidence facts (SHA-256):

- `project_sources.py`: `b4d039843f035e9ab90c6daf8a5d8c2ac50bae2231c7ccb89d8f63377257bfdf`.
- `test_project_sources.py`: `04a8108517c7c848a0f36b88c44fe34ec2b123b9e52ddc9e2f86fbd3003319bb`.
- `material_closure.py`: `ab6fadf3e332e2fa7278c2d34a4d0a5de92c9591d1439957386a28f9a8227dd4`.
- `three-seams-frozen.json`: `c2447b5aff0ad2acdbd8284a0091af991f57d61d3352aec2e12b4b1c867da6e0`.
- `final-service-chain.json`: `ab43950b92c9fcb1516a6dea98d03531a09895d6b9c53ce513c3e195f0663246`.

Relevant actual source excerpts, supplied inline as data:

```python
mapping = next((parts for item, parts in self.source_mappings if item == ref), None)
if mapping is None:
    # The following branches refuse unavailable or mismatched configured refs.
    ...
if (len(raw) != ref.byte_length or hashlib.sha256(raw).hexdigest()
        != ref.capture.content_digest.hex):
    raise ApplicationError("SOURCE_CONTENT_MISMATCH")
```

The two-version test's exact acceptance assertions are:

```python
assert reader.read(_context(), old_ref) == old
assert reader.read(_context(), new_ref) == new
```

The snippet ellipsis only omits refusal branches; it is not an alternative
implementation or unexecuted success path. The independent non-author review
checks the source identities, complete branches and test result before the
model invocation. These facts do not claim that model review has passed.

## Boundaries, unknowns and acceptance

No public SourceRef/SourceMaterialPort change, access expansion, project/Git
scan, source write, archive, credential creation, Product assembly, method
execution, Unit/Pi generation or human Grant is part of this change. Current
files can later become unavailable or change; the adapter will then refuse a
fresh read. It does not guarantee lifelong historical retrieval or establish
file ownership/production ACLs. Host-selected scope/mappings are trusted local
composition, not authentication obtained from a digest or captured actor DTO.

Acceptance for this design is the finite behavior in C1-C4 plus the listed
refusal boundaries. The original nonpassing JEV trial remains unchanged and
is not evidence that this candidate passes. The independent review and the new
JEV invocation must assess these exact inputs under the unchanged substantive
quality criteria. A nonpassing/unknown review must block association/Package
advancement. Provider rationale is unavailable in the current native finite
choice contract; do not manufacture detailed findings from a choice alone.

This candidate makes no claim about full Product delivery, installed wheels,
production auth, inaccessible historical versions or implementation execution.

## Itemized review boundary

This input proposes no production authority or new review engine. Method 2.7.2 fixes eight required pair-level checks. The caller supplies each claim and exact cited text separately; JEV supplies only a finite choice per check. Existing Engineering owners bind original native answers to materials and aggregate all required results. Neither caller assertions nor retrievable citations are automatically accepted. Missing items refuse; unknown never passes. Complex design reasoning belongs to the author and independent reviewer agents. This material does not claim that the new itemized code has already passed real JEV review.
