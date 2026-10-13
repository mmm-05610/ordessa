from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError

def apply_proposal_text(baseline, proposal):
    target_text = baseline.get('text')
    if type(target_text) is not str:
        raise EngineeringError('application_baseline_text_missing')
    for retained in proposal.get('retained_constraints', []):
        locator = retained.get('did_locator')
        exact_text = retained.get('exact_text')
        matching_lines = [line for line in target_text.splitlines() if type(locator) is str and line.startswith(f'{locator}:')]
        if len(matching_lines) != 1 or matching_lines[0] != exact_text:
            raise EngineeringError('application_retained_constraint_conflict')
    for change in proposal.get('changes', []):
        locator = change.get('did_locator')
        exact_before = change.get('before_text')
        matching_lines = [line for line in target_text.splitlines() if type(locator) is str and line.startswith(f'{locator}:')]
        if change.get('operation') != 'modify' or len(matching_lines) != 1 or matching_lines[0] != exact_before or (type(change.get('after_text')) is not str) or ('\n' in change['after_text']) or ('\r' in change['after_text']):
            raise EngineeringError('application_change_conflict')
        lines = target_text.splitlines(keepends=True)
        match_index = next((index for index, line in enumerate(lines) if line.rstrip('\r\n') == exact_before))
        ending = '\r\n' if lines[match_index].endswith('\r\n') else '\n' if lines[match_index].endswith('\n') else ''
        lines[match_index] = change['after_text'] + ending
        target_text = ''.join(lines)
    return target_text
