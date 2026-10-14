"""Build principals and document ACLs.

OrgForge Slack titles are channel names, including #dm_* threads. Jira is
restricted to roles that the OrgForge perspective questions grant `jira`.
Confluence pages use the id prefix (CONF-ENG, CONF-MKT, ...).

EnterpriseRAG's public parquet has no channel, author, or timestamp. Its ACL
is source-level and marked as such.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from contextledger.models import Principal, SourceDoc

DEPT_ROLE = {
    "Engineering_Backend": "engineering_backend",
    "Engineering_Mobile": "engineering_mobile",
    "QA_Support": "qa_support",
    "Product": "product",
    "Sales_Marketing": "sales_marketing",
    "HR_Ops": "hr_ops",
    "Design": "design",
    "Finance": "finance",
    "CEO": "ceo",
}

# Roles that never appear in the perspective questions.
FALLBACK_ROLE_SOURCES = {
    "design": {"confluence", "slack", "email", "zoom"},
    "finance": {"confluence", "slack", "email"},
    "ceo": {"confluence", "jira", "slack", "email", "zoom", "datadog", "git"},
    # People who only show up in company-wide Slack still need a readable role.
    "employee": {"confluence", "slack", "email"},
}

COMPANY_SLACK = {"#digital-hq", "#general", "#incidents", "#standup", "#system-alerts"}


def channel_of(title: str) -> str:
    if not title.startswith("#"):
        return ""
    return title.split()[0].rstrip(":：,.")
DEPT_SLACK = {
    "#engineering_backend": {"engineering_backend"},
    "#engineering_mobile": {"engineering_mobile"},
    "#engineering": {"engineering_backend", "engineering_mobile"},
    "#sales_marketing": {"sales_marketing"},
    "#design": {"design"},
    "#product": {"product"},
    "#hr_ops": {"hr_ops"},
    "#qa_support": {"qa_support"},
}

CHANNEL_DEPT = {
    "#engineering_backend": "Engineering_Backend",
    "#engineering_mobile": "Engineering_Mobile",
    "#sales_marketing": "Sales_Marketing",
    "#design": "Design",
    "#product": "Product",
    "#hr_ops": "HR_Ops",
    "#qa_support": "QA_Support",
}

CONF_PREFIX_DEPT = {
    "QA": "QA_Support",
    "MKT": "Sales_Marketing",
    "PROD": "Product",
    "HR": "HR_Ops",
    "DESIGN": "Design",
}

CONF_PREFIX_ROLES = {
    "ENG": {"engineering_backend", "engineering_mobile", "product"},
    "QA": {"qa_support", "engineering_backend", "engineering_mobile"},
    "MKT": {"sales_marketing"},
    "PROD": {"product"},
    "HR": {"hr_ops"},
    "DESIGN": {"design"},
    "RETRO": None,
}

ERAG_ROLE_SOURCES = {
    "engineer": {"confluence", "jira", "slack", "google_drive"},
    "security": {"confluence", "jira", "slack", "google_drive"},
    "contractor": {"slack", "google_drive"},
    "sales": {"confluence", "slack", "google_drive"},
}


def role_sources_from_questions(questions: list[dict]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {role: set(sources) for role, sources in FALLBACK_ROLE_SOURCES.items()}
    for question in questions:
        role = question.get("actor_role")
        access = question.get("subsystem_access")
        if not role or not isinstance(access, list):
            continue
        found.setdefault(role, set()).update(str(item) for item in access)
    return found


def _mode(counter: Counter) -> str:
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def orgforge_principals(docs: list[SourceDoc], snapshot: dict) -> list[Principal]:
    dept_counts: dict[str, Counter] = defaultdict(Counter)
    for doc in docs:
        if doc.corpus != "orgforge":
            continue
        if doc.dept:
            for actor in doc.actors:
                dept_counts[actor][doc.dept] += 1
        if doc.source == "slack":
            channel = channel_of(doc.title)
            voted = CHANNEL_DEPT.get(channel)
            if voted:
                for actor in doc.actors:
                    dept_counts[actor][voted] += 1
        if doc.source == "confluence":
            parts = doc.doc_id.split("-")
            voted = CONF_PREFIX_DEPT.get(parts[1]) if len(parts) >= 2 else None
            if voted:
                for actor in doc.actors:
                    dept_counts[actor][voted] += 1

    names = set(dept_counts)
    for doc in docs:
        if doc.corpus == "orgforge":
            names.update(doc.actors)
    for person in snapshot.get("departed_employees") or []:
        names.add(person["name"])
    for person in snapshot.get("new_hires") or []:
        names.add(person["name"])

    departed = {person["name"]: person for person in snapshot.get("departed_employees") or []}
    hired = {person["name"]: person for person in snapshot.get("new_hires") or []}

    principals = []
    for name in sorted(names):
        dept = ""
        if name in departed and departed[name].get("dept"):
            dept = departed[name]["dept"]
        elif name in hired and hired[name].get("dept"):
            dept = hired[name]["dept"]
        else:
            dept = _mode(dept_counts[name])
        role = DEPT_ROLE.get(dept, "employee")
        active_from = 0
        active_until = None
        if name in hired:
            active_from = int(hired[name]["day"])
        if name in departed:
            # Departure day is the first day they are gone.
            active_until = int(departed[name]["day"]) - 1
            if name not in hired:
                active_from = min(active_from, int(departed[name]["day"]) - 1)
        principals.append(
            Principal(
                corpus="orgforge",
                principal_id=f"orgforge:{name}",
                name=name,
                role=role,
                dept=dept,
                active_from=active_from,
                active_until=active_until,
            )
        )
    return principals


def enterpriserag_principals() -> list[Principal]:
    roster = [
        ("engineer", "Redwood Engineer", "Engineering"),
        ("security", "Redwood Security", "Security"),
        ("contractor", "Redwood Contractor", "External"),
        ("sales", "Redwood Sales", "Sales"),
    ]
    return [
        Principal(
            corpus="enterpriserag",
            principal_id=f"enterpriserag:{role}",
            name=name,
            role=role,
            dept=dept,
        )
        for role, name, dept in roster
    ]


def _by_name(principals: list[Principal]) -> tuple[dict[str, Principal], dict[str, list[Principal]]]:
    by_full = {}
    by_first: dict[str, list[Principal]] = defaultdict(list)
    for principal in principals:
        by_full[principal.name.lower()] = principal
        by_first[principal.name.split()[0].lower()].append(principal)
    return by_full, by_first


def _dm_principals(channel: str, by_full: dict[str, Principal], by_first: dict[str, list[Principal]]) -> list[Principal]:
    raw = channel[4:] if channel.startswith("#dm_") else channel.lstrip("#")
    tokens = [token for token in raw.split("_") if token]
    found: list[Principal] = []
    seen: set[str] = set()
    index = 0
    while index < len(tokens):
        if index + 1 < len(tokens):
            full = f"{tokens[index]} {tokens[index + 1]}"
            principal = by_full.get(full)
            if principal is not None:
                if principal.principal_id not in seen:
                    found.append(principal)
                    seen.add(principal.principal_id)
                index += 2
                continue
        for principal in by_first.get(tokens[index], []):
            if principal.principal_id not in seen:
                found.append(principal)
                seen.add(principal.principal_id)
        index += 1
    return found


def _actors_as_principals(doc: SourceDoc, by_full: dict[str, Principal]) -> list[Principal]:
    found = []
    for actor in doc.actors:
        principal = by_full.get(actor.lower())
        if principal is not None:
            found.append(principal)
    return found


def _with_source(principals: list[Principal], role_sources: dict[str, set[str]], source: str) -> list[Principal]:
    return [principal for principal in principals if source in role_sources.get(principal.role, set())]


def assign_orgforge_acl(
    doc: SourceDoc,
    principals: list[Principal],
    role_sources: dict[str, set[str]],
) -> tuple[list[str], str]:
    org = [principal for principal in principals if principal.corpus == "orgforge"]
    by_full, by_first = _by_name(org)
    allowed: dict[str, Principal] = {}

    def add(people: list[Principal]) -> None:
        for principal in people:
            allowed[principal.principal_id] = principal

    if doc.source == "slack":
        channel = channel_of(doc.title)
        doc.extra["channel"] = channel
        if channel.startswith("#dm_"):
            people = _dm_principals(channel, by_full, by_first)
            add(people)
            add(_actors_as_principals(doc, by_full))
            return sorted(allowed), "slack_dm" if people else "slack_dm_unresolved"
        roles = DEPT_SLACK.get(channel)
        if roles is not None:
            add([principal for principal in org if principal.role in roles])
            add(_actors_as_principals(doc, by_full))
            return sorted(allowed), "slack_dept_channel"
        if channel in COMPANY_SLACK or channel == "":
            add(_with_source(org, role_sources, "slack"))
            return sorted(allowed), "slack_company_channel"
        add(_with_source(org, role_sources, "slack"))
        return sorted(allowed), "slack_unknown_channel"

    if doc.source == "jira":
        jira_roles = _with_source(org, role_sources, "jira")
        if doc.dept:
            add([principal for principal in jira_roles if principal.dept == doc.dept or principal.role == "product"])
        else:
            add(jira_roles)
        add(_actors_as_principals(doc, by_full))
        return sorted(allowed), "jira_dept_and_role"

    if doc.source == "confluence":
        prefix = ""
        parts = doc.doc_id.split("-")
        if len(parts) >= 2:
            prefix = parts[1]
        roles = CONF_PREFIX_ROLES.get(prefix, None)
        if prefix not in CONF_PREFIX_ROLES:
            add(_with_source(org, role_sources, "confluence"))
            add(_actors_as_principals(doc, by_full))
            return sorted(allowed), "confluence_role"
        if roles is None:
            add(_with_source(org, role_sources, "confluence"))
        else:
            add([principal for principal in org if principal.role in roles])
        add(_actors_as_principals(doc, by_full))
        return sorted(allowed), f"confluence_{prefix.lower()}"

    add(_with_source(org, role_sources, doc.source))
    return sorted(allowed), "source_role"


def assign_enterpriserag_acl(doc: SourceDoc, principals: list[Principal]) -> tuple[list[str], str]:
    allowed = [
        principal.principal_id
        for principal in principals
        if principal.corpus == "enterpriserag" and doc.source in ERAG_ROLE_SOURCES.get(principal.role, set())
    ]
    return sorted(allowed), "source_only_no_channel"


def can_see(principal: Principal, acl: list[str], day: int | None, as_of_day: int | None) -> bool:
    if principal.principal_id not in acl:
        return False
    if as_of_day is None:
        return True
    if day is not None and day > as_of_day:
        return False
    if principal.active_from is not None and as_of_day < principal.active_from:
        return False
    if principal.active_until is not None and as_of_day > principal.active_until:
        return False
    return True
