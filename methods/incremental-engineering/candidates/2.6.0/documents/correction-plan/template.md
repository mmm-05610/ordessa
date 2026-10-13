# Correction plan

This immutable plan describes a proposed ordinary correction before execution.
It is not permission, a Grant, a review result, or proof that any change or
validation has occurred.

## Fixed references

- Approved DID revision: `approved_did_ref`
- Approved implementation package revision: `approved_package_ref`
- Failed submission: `failed_submission_ref`
- Exact failed acceptance ReviewRecord: `failed_review_ref`

The original source must resolve these references and correlate the ReviewRecord
to its completed review command, plan digest, request version, and fence.

## Proposed corrections

For each correction, provide the original failed `failed_check_key` (the exact
ReviewPlan CheckKey with target role/reference, criterion ID, and nullable claim
ID), an exact correction target ArtifactRevisionRef, a concrete change
description, ordered validation steps, and exact references that support the
scope basis. The original source must verify that CheckKey and target against
the complete original ReviewPlan and ReviewRecord observations. This identifies
the failed work item; it does not replace or narrow the new correction-eligibility
review. Do not add fields claiming permission, approval, verified results, or a
Grant.

