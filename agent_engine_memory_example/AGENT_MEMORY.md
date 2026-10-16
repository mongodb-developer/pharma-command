# 🧠 Agent Engine Memory · Pharma Supply Command

![Agent Engine](https://img.shields.io/badge/Agent_Engine-Incident_Memory-A78BFA?style=for-the-badge)
![Python SDK](https://img.shields.io/badge/Python-Public_SDK-38BDF8?style=for-the-badge)
![Connection](https://img.shields.io/badge/Connection-Bring_Your_Own-00ED64?style=for-the-badge)

Drop `agent_memory.py` beside `app.py`. This standalone example uses the public SDK documented with this demo. No actual connection details are included, and the operational app is not modified automatically.

## 🟢 Install and connect

```bash
python3 -m pip install agent-engine-sdk-memory
```

Set `MEMORY_BASE_URL` in the helper to your published **memory backend** URL:

```python
MEMORY_BASE_URL = "http://<container-host>:<published-memory-port>"
```

The agent runner and tool runner are separate endpoints. Do not assume their ports expose memory. From a host process, use the host-mapped memory endpoint; from another container, use the reachable service/network address.

For a local/direct backend, omit `project_id`. Also unset `AGENTIC_MEMORY_PROJECT_ID` so the SDK's environment fallback does not select project routes. Clear unrelated stale SDK credentials from the environment.

```python
from agent_engine_sdk_memory import Memory

memory = Memory(base_url="http://<container-host>:<published-memory-port>")
```

For the managed hosted service, use your own service-account access token and project ID instead:

```python
memory = Memory(
    service_account_token="<service-account-access-token>",
    project_id="<agent-engine-project-id>",
)
```

An authenticated direct backend may use `base_url` plus `service_account_token`, leaving the project route unset. Inside a platform agent, use the runtime-injected `memory` handle rather than constructing another. Never publish real tokens in a repository.

## 🟣 Write an incident

```python
from agent_engine_sdk_memory import Memory
from agent_memory import write_incident_memory

with Memory(base_url=MEMORY_BASE_URL) as memory:
    write_incident_memory(
        memory, incident,
        user_id="demo-operator",  # Replace with your app's established identity
        visibility="private",
    )
```

The helper accepts the app's incident dictionary, binds a stable `pharma:<incident-id>` session, and writes a concise summary with `save_semantic`. Known facts can be saved directly without waiting for LLM extraction from conversation turns. Retrieval/indexing may still lag.

It captures facility, drug, observed coverage, cause, status, quantity, selected donor, and known transfer outcome. It does not copy the whole tool log or invent a delivery outcome. The saved content is a historical snapshot; query operational Atlas data for current inventory and status.

## 🔵 Streamlit integration points

Add these imports and a connection placeholder to `app.py`:

```python
from agent_engine_sdk_memory import Memory
from agent_memory import write_incident_memory

MEMORY_BASE_URL = "http://<container-host>:<published-memory-port>"
```

Then add this helper. It opens/closes a connection for each write and preserves a failure message across Streamlit reruns:

```python
def save_memory_snapshot(incident, user_id):
    try:
        with Memory(base_url=MEMORY_BASE_URL) as memory:
            write_incident_memory(memory, incident, user_id)
    except Exception as exc:
        st.session_state["memory_warning"] = (
            "The incident is saved, but memory sync needs attention "
            f"({type(exc).__name__})."
        )
        return False
    return True
```

After a successful investigation:

```python
incident = investigate(store, facility_id, drug_id)
save_memory_snapshot(incident, user_id="demo-operator")
```

After a successful approval, save the **returned updated incident**:

```python
approved_incident = store.approve(incident["_id"], donor)
save_memory_snapshot(approved_incident, user_id="demo-operator")
```

Replace the existing approval call; do not add a second approval call. Keep the original UI updates and rerun after this block. In the main UI, show any saved warning:

```python
if st.session_state.get("memory_warning"):
    st.warning(st.session_state.pop("memory_warning"))
```

Memory writes are independent of the operational transaction. If memory sync fails after approval, the reservation remains committed. Retry the memory write, not the approval.

## 🟠 Optional conversation history

```python
write_incident_memory(
    memory, incident, user_id="demo-operator", record_turn=True,
)
```

This also calls `record_turn` to store the summary as an assistant turn. Bound identity supplies the user and incident session; `record_turn` accepts no per-call user or visibility. Promotion/extraction happens asynchronously and depends on configured server services.

The semantic save and conversation turn are two separate writes. If the second fails, the first may already exist. Leave conversation recording disabled unless needed.

## 🧩 Retrieve context for the next investigation

```python
from agent_memory import recall_incident_context

context = recall_incident_context(
    memory,
    user_id="demo-operator",
    incident_id=incident["_id"],
    drug_id=incident["drug_id"],
    facility=incident["facility"],
)
print(context.model_dump_json(indent=2))
```

The response is the SDK's structured `ContextResponse`. The helper requests STM, semantic, and episodic sources. STM uses the bound incident session; durable semantic/episodic retrieval can find earlier incidents owned by the same bound user. Query wording requests relevance; it does not enforce an exact drug/facility filter.

No custom metadata filters are included because those require server-side partition/index configuration. Metadata is saved for traceability, and returned chunks carry it under `chunk.metadata.get("metadata", {})` when included in results. Search/indexing is asynchronous, so a successful write may not appear immediately.

## 👥 Private versus project-wide

The example defaults to `private`. Use `visibility="org"` only for incident knowledge intended to be project-visible. Despite the name, `org` does not cross project boundaries.

A bound user plus `visibility="org"` means that user's project-visible records. To search across owners' project-visible records, use the original **unbound, externally constructed** handle:

```python
shared_hits = memory.search_semantic(
    "Previous supplier delays and confirmed transfer outcomes",
    visibility="org",
    top_k=5,
)
```

A runtime-injected handle may inherit ambient identity. To combine personal history with project-visible knowledge, issue separate reads and merge appropriately.

## ⚙️ Avoid duplicate writes

Save on successful business events, not on every Streamlit rerun. Reopening an existing investigation can return the same incident, so the snippets above may write duplicates if used without a guard.

A stable label is useful for identification; this example does **not** assume labels guarantee upserts or idempotency. For a shared app, persist a durable event/write marker or an outbox in the operational database and design retry behavior against your SDK/server's documented guarantees. The example does not implement an outbox or exactly-once delivery.

## 🧪 Run the example

After replacing the endpoint placeholder:

```bash
python3 agent_memory.py
```

It writes one synthetic incident. It does not execute an inventory transfer. Repeated runs may create repeated memory records.

**Validation:** summary construction and public SDK-call arguments were checked locally using a fake SDK handle. Live container connectivity and server-version compatibility must be checked against your own deployment.
