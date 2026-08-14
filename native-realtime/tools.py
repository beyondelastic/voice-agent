"""Health-insurance tools for the native gpt-realtime example.

Sample data lives in the repo-level data/data.json (shared with the agent
example). These are MOCK implementations — no real member data or PHI. In production the functions would call your
claims / eligibility / provider-directory APIs.

This module is SDK-agnostic: it exposes plain functions, JSON-Schema tool
definitions (TOOL_SCHEMAS), and a run_tool() dispatcher. voice_realtime.py
converts TOOL_SCHEMAS into azure.ai.voicelive.models.FunctionTool objects.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# Sample data is shared across both examples in the repo-level data/ folder.
_DATA_PATH = os.path.join(_HERE, os.pardir, "data", "data.json")
with open(_DATA_PATH, encoding="utf-8") as _f:
    _DATA = json.load(_f)

CLAIMS = _DATA["claims"]
COVERAGE = _DATA["coverage"]
PROVIDERS = _DATA["providers"]
MEMBERS = _DATA["members"]


# --- Tool implementations --------------------------------------------------

def get_claim_status(claim_id: str = "", **_):
    """Look up the status of a claim by its id (e.g. CLM-1001)."""
    claim = CLAIMS.get((claim_id or "").upper().strip())
    if not claim:
        return {"found": False, "message": f"No claim found with id '{claim_id}'."}
    return {"found": True, "claim_id": claim_id.upper().strip(), **claim}


def check_benefit_coverage(service: str = "", **_):
    """Check whether a service is covered and its copay."""
    q = (service or "").lower().strip()
    for key, info in COVERAGE.items():
        if key in q or q in key:
            return {"service": key, **info}
    return {"service": service, "covered": None,
            "message": "I don't have that service on file. Please check the plan documents."}


def find_in_network_provider(specialty: str = "", zip_code: str = "", **_):
    """Find in-network providers for a specialty near a ZIP code."""
    providers = PROVIDERS.get((specialty or "").lower().strip())
    if not providers:
        return {"specialty": specialty, "providers": [],
                "message": f"No in-network {specialty} providers found near {zip_code}."}
    return {"specialty": specialty, "zip_code": zip_code, "providers": providers}


def get_deductible_status(member_id: str = "", **_):
    """Report how much of the deductible and out-of-pocket max a member has met."""
    member = MEMBERS.get((member_id or "").upper().strip())
    if not member:
        return {"found": False, "message": f"No member found with id '{member_id}'."}
    return {
        "found": True,
        "plan": member["plan"],
        "deductible_remaining_usd": round(member["deductible_usd"] - member["deductible_met_usd"], 2),
        "out_of_pocket_remaining_usd": round(member["out_of_pocket_max_usd"] - member["out_of_pocket_met_usd"], 2),
        **member,
    }


# --- Tool registry ---------------------------------------------------------

FUNCTIONS = {
    "get_claim_status": get_claim_status,
    "check_benefit_coverage": check_benefit_coverage,
    "find_in_network_provider": find_in_network_provider,
    "get_deductible_status": get_deductible_status,
}

# JSON-Schema tool definitions (converted to SDK tool objects by the caller).
TOOL_SCHEMAS = [
    {
        "name": "get_claim_status",
        "description": "Get the status and details of an insurance claim by its claim id.",
        "parameters": {
            "type": "object",
            "properties": {"claim_id": {"type": "string", "description": "Claim id, e.g. CLM-1001"}},
            "required": ["claim_id"],
        },
    },
    {
        "name": "check_benefit_coverage",
        "description": "Check whether a medical service is covered by the plan and its copay.",
        "parameters": {
            "type": "object",
            "properties": {"service": {"type": "string", "description": "Service, e.g. 'urgent care'"}},
            "required": ["service"],
        },
    },
    {
        "name": "find_in_network_provider",
        "description": "Find in-network providers for a medical specialty near a ZIP code.",
        "parameters": {
            "type": "object",
            "properties": {
                "specialty": {"type": "string", "description": "e.g. 'cardiology', 'primary care'"},
                "zip_code": {"type": "string", "description": "5-digit ZIP code"},
            },
            "required": ["specialty"],
        },
    },
    {
        "name": "get_deductible_status",
        "description": "Get how much of the deductible and out-of-pocket maximum a member has met.",
        "parameters": {
            "type": "object",
            "properties": {"member_id": {"type": "string", "description": "Member id, e.g. M-9087"}},
            "required": ["member_id"],
        },
    },
]


def run_tool(name: str, arguments_json: str) -> str:
    """Execute a tool by name with JSON-string arguments; return a JSON string."""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}
    func = FUNCTIONS.get(name)
    result = func(**args) if func else {"error": f"Unknown tool '{name}'"}
    return json.dumps(result)
