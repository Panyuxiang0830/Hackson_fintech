"""Build explicit, hash-pinned administrator updates for a small demo fixture."""
import hashlib
import json
import re


def plan_annotations(manifest, documents):
    """Return update bodies only for listed resources; never infer new grants."""
    if manifest.get('schema_version') != 1 or manifest.get('authority') != 'team_decision':
        raise ValueError('explicit demo manifest version and authority required')
    entries = manifest.get('documents')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise ValueError('a bounded document allowlist is required')
    ids = [entry.get('doc_id') for entry in entries]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('unique explicit document IDs required')
    project = manifest.get('project', '')
    if not isinstance(project, str) or not project.startswith('demo:'):
        raise ValueError('demo projects require a visible demo: prefix')
    if manifest.get('classification') not in {'internal', 'confidential', 'restricted'}:
        raise ValueError('invalid demo classification')
    departments = manifest.get('allowed_departments')
    if not isinstance(departments, list) or not departments or any(not isinstance(d, str) or not d for d in departments):
        raise ValueError('explicit eligible departments required')
    if not isinstance(manifest.get('scenario_id'), str) or not manifest['scenario_id']:
        raise ValueError('scenario ID required')
    principal = manifest.get('employee_source_principal')
    if not isinstance(principal, str) or not principal.startswith(manifest['corpus'] + ':'):
        raise ValueError('employee principal must belong to the selected corpus')
    rows = {row['doc_id']: row for row in documents if row['corpus'] == manifest['corpus']}
    planned = []
    for entry in entries:
        row = rows.get(entry['doc_id'])
        digest = entry.get('expected_content_hash', '')
        if row is None or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('listed document or pinned content hash missing')
        if row['content_hash'] != digest or hashlib.sha256(row['text'].encode()).hexdigest() != digest:
            raise ValueError('source content changed; review the demo annotation first')
        if type(entry.get('grant_employee')) is not bool:
            raise ValueError('each employee grant must be explicit')
        acl = json.loads(row['acl_json'])
        if entry['grant_employee'] and principal not in acl:
            if row['source'] == 'slack':
                raise ValueError('demo annotations cannot widen Slack participant access')
            acl = sorted([*acl, principal])
        annotation = {'kind': 'manual_demo', 'scenario_id': manifest['scenario_id'],
                      'authority': 'team_decision'}
        extra = json.loads(row['extra_json'])
        if (extra.get('project') == project and extra.get('classification') == manifest['classification']
                and extra.get('allowed_departments') == departments
                and extra.get('permission_annotation') == annotation
                and row['dept'] == manifest['department'] and set(json.loads(row['acl_json'])) == set(acl)):
            continue
        planned.append({'corpus': manifest['corpus'], 'doc_id': row['doc_id'],
            'expected_version': row['version'], 'title': row['title'], 'text': row['text'],
            'project': project, 'department': manifest['department'],
            'classification': manifest['classification'], 'allowed_departments': departments,
            'permission_annotation': annotation, 'acl': acl})
    return planned
