"""Pharma Stockout demo using Streamlit, Strands Agents, and MongoDB Atlas.

Run with your existing Python 3.10+ environment and Streamlit:
    python -m streamlit run stockout.py

Paste your Atlas URI and OpenAI key into the sidebar. Use an Atlas deployment
with Automated Embedding and a database user that can write and create indexes
in the demo database. The source inventory and all case data are synthetic.
Model calls use the OpenAI HTTPS API directly and require no OpenAI Python SDK.
"""

import asyncio
import json
import re
import traceback
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
import streamlit as st
from pymongo import AsyncMongoClient, MongoClient
from pymongo.errors import PyMongoError
from strands import Agent, tool
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider
from strands.memory import MemoryManager
from strands.models.model import Model
from strands.session import SnapshotSessionManager
from strands_mongodb import MongoDBMemoryStore, MongoDBStorage

DATABASE = "pharma_stockout_strands_demo"
MEMORY_NAME = "stockout_resolutions"
MEMORY_SCOPE = "synthetic_pharmacy_network"
AGENT_ID = "pharma-stockout"
MODEL_ID = "gpt-4o-mini"
DRUG = "Cefazolin 1 g vial"
DRUG_ID = "DRG-01"
HISTORICAL_CASE = (
    "Historical case HIST-001. Chicago Medical Center (CHI) ran short of "
    "Cefazolin 1 g vials (DRG-01). Oak Brook Hospital (OAK) transferred "
    "40 units and resolved that shortage. This records a past transfer only."
)
MEMORY_QUERY = "How was the last Chicago Cefazolin shortage for DRG-01 resolved?"
SYSTEM_PROMPT = """You are a read-only inventory analyst for a synthetic pharmacy network.
CHI is Chicago Medical Center. OAK is Oak Brook Hospital.
For current stock, always call get_inventory for each relevant site during the
current turn. When comparing sites, use shortfall_units at the receiving site
and transferable_units at the donor. State how many units the donor can cover
and how many remain outstanding. If asked about a past resolution, call
search_memory using the facility and drug terms. Cite the historical case ID
when it appears in the tool output, and distinguish historic quantities from
current ones. If a lookup fails or returns no match, say what's missing.
Use prior conversation context to resolve references in follow-up questions.
Keep answers to three short sentences. Do not claim to execute transfers."""

STEPS = (
    ("Investigate", "Check Chicago’s current stock for Cefazolin (DRG-01). How many units short is it?"),
    ("Resume the case", "Can Oak Brook cover that shortfall today?"),
    ("Recall and verify", "How did we handle the last Chicago shortage for Cefazolin (DRG-01), and would that work today?"),
)


@dataclass(frozen=True)
class DemoConfig:
    uri: str
    api_key: str
    run_id: str


class OpenAIRequestError(Exception):
    """An OpenAI request failed. The message excludes credentials and response bodies."""


def openai_messages(messages, system_prompt):
    formatted = [{"role": "system", "content": system_prompt}] if system_prompt else []
    for message in messages:
        texts = []
        tool_calls = []
        for block in message["content"]:
            if "toolResult" in block:
                result = block["toolResult"]
                formatted.append({
                    "role": "tool",
                    "tool_call_id": result["toolUseId"],
                    "content": json.dumps({"status": result["status"], "content": result["content"]}),
                })
            if "toolUse" in block:
                call = block["toolUse"]
                tool_calls.append({
                    "type": "function", "id": call["toolUseId"],
                    "function": {"name": call["name"], "arguments": json.dumps(call["input"])},
                })
            if "text" in block:
                texts.append(block["text"])
        if texts or tool_calls:
            item = {"role": message["role"], "content": "\n".join(texts) if texts else None}
            if tool_calls:
                item["tool_calls"] = tool_calls
            formatted.append(item)
    return formatted


class OpenAIChatModel(Model):
    """Text and function calling for this Strands demo over Chat Completions."""

    def __init__(self, api_key):
        self.api_key = api_key
        self.config = {"model_id": MODEL_ID}

    def get_config(self):
        return dict(self.config)

    def update_config(self, **model_config):
        self.config.update(model_config)

    def structured_output(self, *args, **kwargs):
        raise NotImplementedError("This demo uses text and function calls.")

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        request = {
            "model": self.config["model_id"],
            "messages": openai_messages(messages, system_prompt),
            "temperature": 0,
        }
        if tool_specs:
            request["tools"] = [
                {"type": "function", "function": {
                    "name": spec["name"], "description": spec.get("description", ""),
                    "parameters": spec["inputSchema"]["json"],
                }}
                for spec in tool_specs
            ]
        try:
            async with httpx.AsyncClient(timeout=40) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request,
                )
                response.raise_for_status()
            choice = response.json()["choices"][0]
        except httpx.HTTPStatusError as exc:
            raise OpenAIRequestError(f"HTTP {exc.response.status_code}") from None
        except httpx.RequestError:
            raise OpenAIRequestError("network or timeout error") from None
        except (KeyError, IndexError, ValueError):
            raise OpenAIRequestError("unexpected response format") from None

        message = choice["message"]
        yield {"messageStart": {"role": "assistant"}}
        if text := message.get("content") or message.get("refusal"):
            yield {"contentBlockDelta": {"delta": {"text": text}}}
            yield {"contentBlockStop": {}}
        for call in message.get("tool_calls") or []:
            function = call["function"]
            yield {"contentBlockStart": {"start": {"toolUse": {
                "toolUseId": call["id"], "name": function["name"],
            }}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": function["arguments"]}}}}
            yield {"contentBlockStop": {}}
        stop_reason = {"tool_calls": "tool_use", "length": "max_tokens", "content_filter": "content_filtered"}
        yield {"messageStop": {"stopReason": stop_reason.get(choice.get("finish_reason"), "end_turn")}}


def mongo_client(uri):
    return AsyncMongoClient(
        uri, appname="StrandsPharmaStockout", serverSelectionTimeoutMS=8000
    )


def memory_config(**connection):
    return {
        **connection,
        "database": DATABASE,
        "search_type": "vector",
        "index_ready_timeout": 120,
    }


def memory_store(connection, *, writable=False):
    return MongoDBMemoryStore(
        name=MEMORY_NAME, scope=MEMORY_SCOPE, config=connection,
        collection="resolution_memory", writable=writable,
    )


async def seed_demo(uri):
    async with mongo_client(uri) as client:
        inventory = client[DATABASE].inventory
        for facility, on_hand, reserved, quarantined in (
            ("CHI", 70, 10, 0),
            ("OAK", 135, 15, 5),
        ):
            await inventory.update_one(
                {"_id": f"{facility}:{DRUG_ID}"},
                {"$setOnInsert": {
                    "facility_id": facility, "drug_id": DRUG_ID, "drug": DRUG,
                    "on_hand": on_hand, "reserved": reserved,
                    "quarantined": quarantined, "target_units": 100,
                }},
                upsert=True,
            )
        store = memory_store(memory_config(client=client), writable=True)
        try:
            await store.add(HISTORICAL_CASE)
            for attempt in range(25):
                matches = await store.search(MEMORY_QUERY)
                if any(entry.content == HISTORICAL_CASE for entry in matches):
                    return True
                if attempt < 24:
                    await asyncio.sleep(3)
        finally:
            await store.close()
    return False


def inventory_tool(inventory):
    @tool
    def get_inventory(facility_id: str, drug_id: str) -> dict:
        """Get current usable stock, shortfall, and transferable stock from Atlas.

        Args:
            facility_id: CHI for Chicago or OAK for Oak Brook.
            drug_id: The inventory drug code, such as DRG-01.
        """
        facility_id, drug_id = facility_id.strip().upper(), drug_id.strip().upper()
        try:
            record = inventory.find_one(
                {"_id": f"{facility_id}:{drug_id}"},
                {"_id": 0, "drug": 1, "on_hand": 1, "reserved": 1,
                 "quarantined": 1, "target_units": 1},
            )
        except PyMongoError:
            return {"status": "unavailable", "facility_id": facility_id, "drug_id": drug_id}
        if record is None:
            return {"status": "not_found", "facility_id": facility_id, "drug_id": drug_id}

        target = record["target_units"]
        usable = max(0, record["on_hand"] - record["reserved"] - record["quarantined"])
        return {
            "status": "ok",
            "source": "Atlas inventory",
            "facility_id": facility_id,
            "drug_id": drug_id,
            "drug": record["drug"],
            "usable_units": usable,
            "target_units": target,
            "shortfall_units": max(0, target - usable),
            "transferable_units": max(0, usable - target),
        }

    return get_inventory


class ToolTrace(HookProvider):
    def __init__(self):
        self.calls = []

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeToolCallEvent, self.before)
        registry.add_callback(AfterToolCallEvent, self.after)

    def before(self, event):
        self.calls.append({
            "id": event.tool_use["toolUseId"],
            "tool": event.tool_use["name"],
            "input": event.tool_use.get("input", {}),
        })

    def after(self, event):
        call_id = event.tool_use["toolUseId"]
        for call in reversed(self.calls):
            if call["id"] == call_id:
                call["status"] = event.result["status"]
                if event.result["status"] == "success":
                    call["result"] = event.result["content"]
                break


def session_id_for(run_id, step_index):
    suffix = "recall" if step_index == 2 else "case"
    return f"{run_id}-{suffix}"


async def run_turn(config, step_index):
    session_id = session_id_for(config.run_id, step_index)
    prefix = f"session/{session_id}/"
    # Strands initializes both storage and memory in worker event loops. A URI
    # lets their integration allocate loop-local clients. Inventory uses the
    # thread-safe synchronous driver because Strands runs sync tools in workers.
    connection = memory_config(
        connection_string=config.uri,
        client_args={"serverSelectionTimeoutMS": 8000,
                     "appname": f"StrandsStockoutAgent-{uuid4().hex}"},
    )
    storage = MongoDBStorage(connection, collection="agent_sessions")
    with MongoClient(config.uri, appname="StrandsStockoutInventory", serverSelectionTimeoutMS=8000) as client:
        store = memory_store(connection)
        try:
            had_snapshot = any(
                key.endswith("/snapshot_latest.json") for key in await storage.list(prefix)
            )
            if step_index == 1 and not had_snapshot:
                return None

            trace = ToolTrace()
            agent = Agent(
                model=OpenAIChatModel(config.api_key),
                agent_id=AGENT_ID,
                system_prompt=SYSTEM_PROMPT,
                storage=storage,
                session_manager=SnapshotSessionManager(session_id=session_id),
                memory_manager=MemoryManager(stores=[store], injection=False),
                tools=[inventory_tool(client[DATABASE].inventory)],
                hooks=[trace],
                callback_handler=None,
            )
            answer = await asyncio.wait_for(agent.invoke_async(STEPS[step_index][1]), timeout=180)
            saved_keys = await storage.list(prefix)
        finally:
            # Both adapters use the same URI config and connection lifecycle.
            await storage.close()
    return {
        "answer": str(answer), "session": session_id, "had_snapshot": had_snapshot,
        "snapshot": next((key for key in saved_keys if key.endswith("/snapshot_latest.json")), None),
        "calls": trace.calls,
    }


def clear_results():
    st.session_state.pop("results", None)


def show_error_details(error):
    # Omit messages, source text and local values, which could contain credentials.
    lines = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        lines.append(type(error).__name__)
        for frame in traceback.extract_tb(error.__traceback__)[-12:]:
            lines.append(f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}")
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    with st.expander("Error details"):
        st.code("\n".join(lines), language=None)



def show_result(result):
    st.markdown(result["answer"])
    if result["had_snapshot"]:
        st.caption(f"Session {result['session']} · Existing Atlas snapshot")
    else:
        st.caption(f"Session {result['session']} · Fresh conversation")
    if result["snapshot"]:
        st.caption(f"Snapshot saved in Atlas · {result['snapshot']}")
    else:
        st.warning("No saved Atlas snapshot was found for this turn.")
    if result["calls"]:
        with st.expander("Strands tool calls and Atlas results", expanded=True):
            for call in result["calls"]:
                st.code(call["tool"], language=None)
                st.json({key: value for key, value in call.items() if key not in ("id", "tool")})
    else:
        st.warning("The model returned without calling a tool. Run the step again to inspect tool use.")


def main():
    st.set_page_config(page_title="Pharma Stockout | Strands + MongoDB", layout="wide")
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] { background: #001e2b; color: #f5fbf7; }
        [data-testid="stHeader"] { background: #001e2b; }
        [data-testid="stSidebar"] { background: #082f3b; color: #f5fbf7; }
        h1, h2, h3, [data-testid="stMarkdownContainer"] p,
        [data-testid="stWidgetLabel"] p, [data-testid="stCaptionContainer"] p {
            color: #f5fbf7;
        }
        [data-testid="stAlert"] p, .stButton p, .stCode p { color: inherit; }
        [data-testid="stBaseButton-primary"] { background: #00ed64; color: #001e2b; border-color: #00ed64; }
        [data-testid="stBaseButton-secondary"] { background: #082f3b; color: #f5fbf7; border-color: #47717d; }
        [data-testid="stExpander"] details { background: #082f3b; color: #f5fbf7; }
        .demo-brand { color: #00ed64; font-weight: 650; letter-spacing: .04em; }
        </style>
        """, unsafe_allow_html=True,
    )
    with st.sidebar:
        st.header("Connect")
        uri = st.text_input("MongoDB Atlas URI", type="password", on_change=clear_results,
                            placeholder="mongodb+srv://…").strip()
        api_key = st.text_input("OpenAI API key", type="password", on_change=clear_results).strip()
        run_id = st.text_input("Demo run ID", value="demo-01", on_change=clear_results,
                               help="Change this ID for a fresh set of sessions. Reuse it to resume after a restart.").strip()
        st.caption(f"Atlas database · {DATABASE}")
        valid_uri = uri.startswith(("mongodb+srv://", "mongodb://"))
        seed = st.button("Seed demo data", type="primary", disabled=not valid_uri)
        st.caption("The first seed can take a few minutes while Atlas builds the memory index.")
        if uri and not valid_uri:
            st.error("Paste a MongoDB connection URI starting with mongodb+srv:// or mongodb://.")

    st.markdown('<div class="demo-brand">MongoDB Atlas + Strands Agents</div>', unsafe_allow_html=True)
    st.title("Pharma Stockout")
    st.caption("Resume an investigation, recall a past resolution, and verify live stock.")
    if seed:
        with st.spinner("Seeding inventory and waiting for the Atlas Vector Search index…"):
            try:
                ready = asyncio.run(seed_demo(uri))
            except Exception as exc:
                st.error(f"Seed failed ({type(exc).__name__}). Check Atlas access, index privileges, and Automated Embedding. You can safely retry.")
                show_error_details(exc)
            else:
                if ready:
                    st.success("Inventory and historical case HIST-001 are ready.")
                else:
                    st.warning("Inventory is seeded. The historical case is still indexing. Run Seed demo data again to check readiness.")

    valid_run = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", run_id))
    if not valid_run:
        st.warning("Use a run ID of 1–32 letters, numbers, hyphens, or underscores, starting with a letter or number.")
    config = DemoConfig(uri, api_key, run_id)
    enabled = valid_uri and bool(api_key) and valid_run
    results = st.session_state.setdefault("results", {})
    for index, (title, question) in enumerate(STEPS):
        st.subheader(f"{index + 1}. {title}")
        st.write(question)
        if st.button(title, key=f"step-{index}", disabled=not enabled):
            results.pop(index, None)
            with st.spinner("Running a fresh Strands agent…"):
                try:
                    result = asyncio.run(run_turn(config, index))
                except OpenAIRequestError as exc:
                    st.error(f"OpenAI request failed ({exc}). Check the key, model access, and account quota.")
                except PyMongoError as exc:
                    st.error(f"Atlas request failed ({type(exc).__name__}). Check database permissions and network access.")
                    show_error_details(exc)
                except Exception as exc:
                    st.error(f"Step failed ({type(exc).__name__}). Expand Error details to see where the step stopped.")
                    show_error_details(exc)
                else:
                    if result is None:
                        st.info("Run Investigate first to create the case snapshot for this run ID.")
                    else:
                        results[index] = result
        if index in results:
            show_result(results[index])


if __name__ == "__main__":
    main()
