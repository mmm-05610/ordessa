from __future__ import annotations
from typing import Any
from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_to_dict

def review_judgement_to_dict(judgement) -> dict[str, Any]:
    return {'verdict': judgement.verdict, 'decision_run_ref': material_ref_to_dict(judgement.decision_run_ref), 'answer_digest': judgement.answer_digest, 'policy_ref': material_ref_to_dict(judgement.policy_ref), 'check_receipt_refs': [material_ref_to_dict(ref) for ref in judgement.check_receipt_refs], 'registry_ref': dict(judgement.registry_ref)}
