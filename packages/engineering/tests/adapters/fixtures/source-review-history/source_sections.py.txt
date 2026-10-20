"""Pinned host selection of complete Markdown sections for source review.

This is an input representation, not method policy or an evidence authority.
The original complete captures and caller excerpts are still verified before use.
"""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from hashlib import sha256
import re

from ordessa_infrastructure.encoding import canonical_bytes
from ...application.contracts.errors import ApplicationError

CONTRACT = 'engineering-source-review/sections/1'
INSTRUCTIONS = (
    'The host verified the COMPLETE original baseline and candidate captures against their '
    'SourceRefs. Only the explicitly selected COMPLETE sections are visible in this question, '
    'not the entire documents. Each source section names its original member, heading, UTF-8 '
    'range and digest. source_text_blocks contains its actual readable text; no external lookup '
    'is needed. Equal text blocks preserve every separate source and member occurrence. '
    'related_sections is the explicit cross-document context selection for this check; '
    'selection_by_check binds the selections across all eight checks. Unselected sections '
    'remain outside this question and must not be assumed reviewed. caller_evidence contains '
    'the original quoted evidence with ALL exact original locations; caller_evidence_occurrences '
    'preserves its original order and multiplicity. Selected sections are interpretation context '
    'only: passed still requires the original caller excerpts to support the judgment under '
    'the unchanged method criteria and instructions. Missing support means unknown, not passed.')


def complete_sections(text):
    """Index whole heading subtrees, bounded by original composite member fences.

    Fenced code is never interpreted as headings. Prelude and member marker text
    are also addressable whole sections, so source identity excerpts remain visible.
    """
    raw = text.encode('utf-8')
    headings, special, offset, member, fenced = [], [], 0, None, None
    body_start = 0
    regions = []
    for line in text.splitlines(keepends=True):
        end = offset + len(line.encode('utf-8'))
        inside = fenced is not None
        if inside:
            marker, width = fenced
            if re.fullmatch(r' {0,3}' + re.escape(marker) + '{' + str(width) + r',}[ \t]*(?:\r?\n)?', line):
                fenced = None
        else:
            fence = re.match(r'^ {0,3}(`{3,}|~{3,})([^\r\n]*)', line)
            if fence and (fence[1][0] == '~' or '`' not in fence[2]):
                fenced = fence[1][0], len(fence[1])
        match = None if inside or fenced else re.match(r'^(#{1,6}) (.+?)\s*$', line)
        if match:
            marker = re.fullmatch(r'(BEGIN|END) MEMBER (.+)', match[2])
            if marker:
                regions.append((body_start, offset, member))
                special.append((offset, end, marker[2], line.rstrip()))
                if marker[1] == 'BEGIN':
                    if member is not None:
                        raise ApplicationError('REVIEW_SECTION_BOUNDARY_INVALID')
                    member = marker[2]
                else:
                    if member != marker[2]:
                        raise ApplicationError('REVIEW_SECTION_BOUNDARY_INVALID')
                    member = None
                body_start = end
            else:
                headings.append((offset, len(match[1]), member, line.rstrip()))
        offset = end
    if member is not None:
        raise ApplicationError('REVIEW_SECTION_BOUNDARY_INVALID')
    regions.append((body_start, len(raw), None))
    spans = [(*row, 'member_marker') for row in special]
    for start, end, region_member in regions:
        rows = [row for row in headings if start <= row[0] < end]
        if start < (rows[0][0] if rows else end):
            spans.append((start, rows[0][0] if rows else end, region_member, None, 'preamble'))
        for index, (position, level, row_member, heading) in enumerate(rows):
            stop = next((row[0] for row in rows[index + 1:] if row[1] <= level), end)
            spans.append((position, stop, row_member, heading, 'chapter'))
            # Document identity tables precede the first chapter. Preserve this
            # whole front matter explicitly; never label it the entire document.
            if level == 1 and index + 1 < len(rows) and rows[index + 1][0] < stop:
                spans.append((position, rows[index + 1][0], row_member, heading, 'front_matter'))
    result = []
    for index, (start, end, section_member, heading, kind) in enumerate(sorted(spans, key=lambda row:(row[0], -row[1]))):
        result.append({'section_id': 's' + str(index), 'member': section_member,
                       'heading': heading, 'kind': kind, 'byte_start': start, 'byte_end': end,
                       'sha256': sha256(raw[start:end]).hexdigest()})
    return result


def validate_selection(document, source_inputs, *, scope, method_ref, check_ids):
    """Compile an exact trusted-host manifest; never repair or infer its selection."""
    try:
        if (type(document) is not dict
                or set(document) != {'contract', 'scope', 'method_ref', 'sources', 'checks'}
                or document['contract'] != CONTRACT or document['scope'] != scope
                or document['method_ref'] != method_ref
                or type(document['sources']) is not list or len(document['sources']) != 2
                or type(document['checks']) is not list
                or tuple(row['check_id'] for row in document['checks']) != tuple(check_ids)):
            raise ValueError
        indexes = {}
        for given, source in zip(document['sources'], source_inputs):
            if given != {'role': source['role'], 'source_ref': source['source_ref']}:
                raise ValueError
            indexes[source['role']] = {row['section_id']: row for row in complete_sections(source['text'])}
        compiled = {}
        for check in document['checks']:
            if (set(check) != {'check_id', 'related_sections'}
                    or type(check['related_sections']) is not list or not check['related_sections']):
                raise ValueError
            sections, seen = [], set()
            for chosen in check['related_sections']:
                if type(chosen) is not dict or set(chosen) != {'role', 'section'}:
                    raise ValueError
                role, section = chosen['role'], chosen['section']
                if (type(section) is not dict
                        or canonical_bytes(indexes[role].get(section['section_id'])) != canonical_bytes(section)):
                    raise ValueError
                key = role, section['section_id']
                if key in seen:
                    raise ValueError
                seen.add(key)
                sections.append(deepcopy(chosen))
            # Each pair-level judgment keeps explicit context for both sources.
            if {row['role'] for row in sections} != set(indexes):
                raise ValueError
            for role in indexes:
                spans = sorted((row['section']['byte_start'], row['section']['byte_end'])
                               for row in sections if row['role'] == role)
                if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
                    raise ValueError
            compiled[check['check_id']] = sections
        return compiled
    except (KeyError, TypeError, ValueError, IndexError):
        raise ApplicationError('REVIEW_SECTION_SELECTION_INVALID') from None


def pack_sections(selection, source_inputs, evidence, check_id):
    """Keep complete selected text plus every original cited occurrence."""
    sections = selection[check_id]
    blocks, ids, sources = {}, {}, []
    for source in source_inputs:
        raw, visible = source['text'].encode('utf-8'), []
        for chosen in sections:
            if chosen['role'] != source['role']:
                continue
            section = chosen['section']
            text = raw[section['byte_start']:section['byte_end']].decode('utf-8', 'strict')
            if text not in ids:
                ids[text] = 'b' + str(len(blocks)); blocks[ids[text]] = text
            visible.append({**section, 'block_id': ids[text]})
        sources.append({'role': source['role'], 'source_ref': deepcopy(source['source_ref']),
                        'selected_sections': visible})
    unique, occurrences, seen = [], [], {}
    for entry in evidence:
        matched = [source for source in sources if source['source_ref'] == entry['source_ref']]
        if matched:
            # All literal occurrences in either DID member must be in complete
            # selected sections; duplicate SRS/SDD quotations cannot lose identity.
            spans = sorted((section['byte_start'], section['byte_end'])
                           for section in matched[0]['selected_sections'])
            starts = [span[0] for span in spans]
            for location in entry['locations']:
                index = bisect_right(starts, location['byte_start']) - 1
                if index < 0 or spans[index][1] < location['byte_end']:
                    raise ApplicationError('REVIEW_SECTION_EVIDENCE_UNCOVERED')
        key = canonical_bytes(entry)
        if key not in seen:
            seen[key] = len(unique); unique.append(deepcopy(entry))
        occurrences.append(seen[key])
    return {'sources': sources, 'source_text_blocks': blocks,
            'caller_evidence': unique, 'caller_evidence_occurrences': occurrences,
            'related_sections': deepcopy(sections),
            'selection_by_check': {key: [{'role': row['role'],
                'section_id': row['section']['section_id']} for row in rows]
                for key, rows in selection.items()}}
