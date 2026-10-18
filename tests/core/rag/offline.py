"""Network-free stand-ins for the nodes that call an LLM or the database."""


async def _understand(state):
    return {}


async def _agents(state):
    case_id = state.get("requested_case_id")
    return {"evidence": [], "resolved_case_ids": [case_id] if case_id else []}


OFFLINE_NODES = {"understand": _understand, "agents": _agents}
