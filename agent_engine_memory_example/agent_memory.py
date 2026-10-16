"""Agent Engine Memory example for Pharma Supply Command (Python 3.10+).
Install: python3 -m pip install agent-engine-sdk-memory
Edit MEMORY_BASE_URL, then: python3 agent_memory.py
Uses public APIs from the supplied SDK documentation. No live endpoint tested.
"""
import json
from datetime import datetime, timezone
from agent_engine_sdk_memory import Memory, MemoryRequestContext

# Published MEMORY backend endpoint, not the agent/tool runner endpoint.
MEMORY_BASE_URL = "http://<container-host>:<published-memory-port>"


def summarize_incident(incident):
    """Extract relevant facts from the original app's incident dictionary."""
    incident_id = incident.get("_id") or incident.get("incident_id")
    if not incident_id:
        raise ValueError("Incident needs _id or incident_id")
    fields = ("facility", "inventory_id", "drug_id", "drug", "days_supply",
              "causes", "quantity", "status", "created_at", "approved_at")
    facts = {key: incident[key] for key in fields if key in incident}
    facts.update(incident_id=str(incident_id), source="Synthetic pharmacy demo",
                 recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    donor = incident.get("selected_donor") or {}
    if donor:
        facts["selected_donor"] = {key: donor[key] for key in
            ("facility", "inventory_id", "eta_hours", "donor_days_after") if key in donor}
    transfer = incident.get("transfer") or {}
    if transfer:
        facts["transfer"] = {key: transfer[key] for key in
            ("quantity", "status", "recipient_received") if key in transfer}
    if incident.get("decision_reason"):
        facts["human_stated_reason"] = incident["decision_reason"]
    status = incident.get("status", "Unknown")
    outcomes = {
        "Transfer reserved": "Approved and reserved; delivery and stockout resolution are NOT confirmed.",
        "Awaiting approval": "Transfer proposed; human approval and delivery are NOT confirmed.",
        "Escalation required": "No eligible donor found under demo rules; manual review required.",
        "Healthy": "Coverage above alert threshold at investigation time; no transfer proposed.",
    }
    facts["outcome_summary"] = outcomes.get(status, "Only the recorded status is known; no further outcome inferred.")
    text = ("Historical pharmacy incident snapshot; query operational Atlas data for current status.\n"
            + json.dumps(facts, indent=2, ensure_ascii=False))
    return text, facts


def bind_incident(memory, user_id, incident_id):
    if not str(user_id or "").strip() or not str(incident_id or "").strip():
        raise ValueError("Nonempty user_id and incident_id are required")
    return memory.bind(MemoryRequestContext(
        user_id=str(user_id), session_id=f"pharma:{incident_id}"))


def write_incident_memory(memory, incident, user_id, *, visibility="private", record_turn=False):
    """Save a known fact directly; optional second write to conversation history.

    Accepts an externally constructed or runtime-injected Memory handle.
    Caller owns retry/deduplication: labels are NOT assumed to be upsert keys.
    """
    if visibility not in ("private", "org"):
        raise ValueError("visibility must be private or org")
    text, facts = summarize_incident(incident)
    session = bind_incident(memory, user_id, facts["incident_id"])
    metadata = {"incident_id": facts["incident_id"],
                "status": incident.get("status", "Unknown"), "source": "pharma_supply_command"}
    result = session.save_semantic(
        text=text,
        label=f"pharma:{facts['incident_id']}:{metadata['status']}",
        visibility=visibility,
        metadata=metadata,
    )
    if record_turn:
        # This is a separate write, not atomic with save_semantic.
        # Identity is inherited from bind(); record_turn takes no visibility.
        session.record_turn(role="assistant", content=text, metadata=metadata)
    return result


def recall_incident_context(memory, user_id, incident_id, drug_id, facility):
    session = bind_incident(memory, user_id, incident_id)
    return session.build_context(
        query=(f"Previous pharmacy supply disruptions involving drug {drug_id} "
               f"or facility {facility}: decisions and confirmed outcomes."),
        enabled_sources={"stm", "semantic", "episodic"},
        max_tokens=2048,
    )


EXAMPLE_INCIDENT = {
    "_id": "INC-EXAMPLE-001", "inventory_id": "CHI:DRG-01",
    "facility": "Chicago Medical Center", "drug_id": "DRG-01",
    "drug": "Cefazolin 1 g vial", "days_supply": 0.75,
    "causes": ["Supplier delay"], "quantity": 135, "status": "Transfer reserved",
    "selected_donor": {"facility": "Oak Brook Hospital", "inventory_id": "OAK:DRG-01"},
    "transfer": {"quantity": 135, "status": "Reserved; awaiting simulated dispatch",
                 "recipient_received": False},
}


if __name__ == "__main__":
    if "<" in MEMORY_BASE_URL:
        raise SystemExit("Set MEMORY_BASE_URL to your published memory backend URL first.")
    # Local/direct route: leave project_id unset (including environment fallback).
    with Memory(base_url=MEMORY_BASE_URL) as memory:
        write_incident_memory(memory, EXAMPLE_INCIDENT, user_id="demo-operator")
        print("Memory write acknowledged. Search visibility may lag behind indexing.")
        # Optional retrieval; an immediate search may not see the new write yet:
        # context = recall_incident_context(memory, "demo-operator",
        #     EXAMPLE_INCIDENT["_id"], "DRG-01", "Chicago Medical Center")
        # print(context.model_dump_json(indent=2))
