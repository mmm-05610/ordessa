"""Validate the frozen domain plan without credentials or network calls.

Historical labels remain unchanged; distinct domains must not all be compiled
into six TaskGate questions with generic acceptance criteria.
"""
import json
from pathlib import Path
from live_acceptance import prepare as prepare_plan


def prepare():
    plan = json.loads(Path(__file__).with_name('domain-cases-v2.json').read_text())
    result = prepare_plan(plan)
    result.update(allowed_attempts=0, real_model_requests=0,
                  note='Preparation does not authorize live requests. Historical labels remain unchanged.')
    return result


if __name__ == '__main__': print(json.dumps(prepare(), ensure_ascii=False, indent=2))
