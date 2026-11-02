"""Deterministic tools exposed to an agent."""
from audit.common import system_of


def _error(code, message):
    return {"ok": False, "error": {"code": code, "message": message}, "matches": []}


def _observation_match(observation, query):
    context = observation.get("ctx") or {}
    searchable = [
        observation["file"],
        observation["rid"],
        observation["state"],
        observation["t"],
        observation["cap"],
        *[str(value) for value in context.values()],
        *[str(identifier) for identifier in observation["ids"]],
    ]
    return query in " ".join(searchable).casefold()


def _observation_excerpt(observation):
    context = observation.get("ctx") or {}
    source = context.get("src", "observation")
    return "resource_id={rid}; state={state}; source={source}".format(
        rid=observation["rid"], state=observation["state"], source=source
    )


def search_evidence(case_id, query, state):
    """Search parsed evidence associated with a case.

    ``state`` is injected by the backend and is not part of the model-facing
    tool schema. Results contain only fields produced by the existing parser.
    """
    if not isinstance(case_id, str) or not case_id.strip():
        return _error("INVALID_CASE_ID", "case_id must be a non-empty string")
    if case_id not in state.cases:
        return _error("CASE_NOT_FOUND", "No deletion request exists for case_id '%s'" % case_id)
    if not isinstance(query, str) or not query.strip():
        return _error("INVALID_QUERY", "query must be a non-empty string")

    engine = state.engine
    query = query.casefold().strip()
    resource_ids = set(engine.linked(engine.ids[case_id]))
    resource_ids.update(engine.account.get(case_id, []))
    resource_ids.update(engine.anon.get(case_id, []))

    matches = []
    for resource_id in sorted(resource_ids):
        for observation in engine.ev.obs.get(resource_id, []):
            if not _observation_match(observation, query):
                continue
            matches.append({
                "evidence_id": observation["file"],
                "resource_id": resource_id,
                "system_id": system_of(resource_id),
                "timestamp": observation["t"],
                "excerpt": _observation_excerpt(observation),
            })

    for system, coverages in engine.ev.cover.items():
        for coverage in coverages:
            if not (resource_ids & coverage["rids"]):
                continue
            searchable = " ".join(
                [coverage["file"], system, coverage["t"], coverage["cap"]]
            ).casefold()
            if query not in searchable:
                continue
            matches.append({
                "evidence_id": coverage["file"],
                "resource_id": "",
                "system_id": system,
                "timestamp": coverage["t"],
                "excerpt": "coverage system_id=%s; resources=%d"
                % (system, len(coverage["rids"])),
            })

    matches.sort(key=lambda match: (match["timestamp"], match["evidence_id"], match["resource_id"]))
    return {"ok": True, "matches": matches}
