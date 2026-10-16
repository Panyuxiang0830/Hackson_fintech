"""Explicit project assignments for a bounded, reviewed corpus subset."""
import hashlib
import json
import re


def plan_project_annotations(manifest, documents):
    if manifest.get('schema_version') != 1 or manifest.get('authority') != 'team_decision':
        raise ValueError('explicit project manifest required')
    corpus = manifest.get('corpus')
    projects = manifest.get('projects')
    if not isinstance(corpus, str) or not isinstance(projects, list) or not 1 <= len(projects) <= 20:
        raise ValueError('bounded project catalog required')
    rows = {r['doc_id']: r for r in documents if r['corpus'] == corpus}
    seen, project_ids, planned = set(), set(), []
    for project in projects:
        pid, name = project.get('id'), project.get('name')
        if (not isinstance(pid, str) or not pid.startswith(corpus + ':') or pid in project_ids
                or not isinstance(name, str) or not name.strip() or len(name) > 120):
            raise ValueError('invalid or duplicate project')
        project_ids.add(pid)
        entries = project.get('documents')
        if not isinstance(entries, list) or not entries:
            raise ValueError('project needs explicitly selected resources')
        for entry in entries:
            doc_id, digest = entry.get('doc_id'), entry.get('expected_content_hash')
            if doc_id in seen or doc_id not in rows or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('missing or duplicate resource/hash')
            seen.add(doc_id)
            if len(seen) > 50:
                raise ValueError('too many selected resources')
            row = rows[doc_id]
            if row['content_hash'] != digest or hashlib.sha256(row['text'].encode()).hexdigest() != digest:
                raise ValueError('source content changed; review project assignment')
            extra = json.loads(row['extra_json'])
            if extra.get('project', '') not in {'', pid, project.get('previous_project')}:
                raise ValueError('resource already belongs to another project')
            annotation = {'kind':'administrator_policy', 'authority':'team_decision', 'scenario_id':'project-catalog-20261016'}
            if extra.get('project') == pid and extra.get('project_name') == name and extra.get('permission_annotation') == annotation:
                continue
            planned.append({'corpus':corpus, 'doc_id':doc_id, 'expected_version':row['version'],
                            'title':row['title'], 'text':row['text'],
                            'project':pid, 'project_name':name, 'permission_annotation':annotation})
    return planned
