"""The complete Agent Engine registration and model/tool loop for ONE tool."""
import json
import os
from agent_engine_sdk_langgraph import App
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from stockout_agent.stockout import check_stockout

app = App(app_name="pharma-stockout-tool")


# 1. Register a normal, typed Python function as a custom Agent Engine tool.
@app.tool()
def check_stockout_risk(facility_id: str, drug_id: str, threshold_days: float = 2.0) -> str:
    """Check current usable drug inventory and stockout risk at a facility.

    Use this when asked whether a facility is running low on a specific drug.
    facility_id is the facility code (CHI=Chicago, OAK=Oak Brook).
    drug_id is the catalog identifier (DRG-01=Cefazolin 1 g vial).
    threshold_days is the alert cutoff; default two days.
    Returns JSON with status, data source, usable stock, coverage, and risk.
    This lookup does not reserve, transfer, or dispense inventory.
    """
    return json.dumps(check_stockout(facility_id, drug_id, threshold_days))


@app.entrypoint
def build_agent():
    # 2. Keep model calls inside the SDK wrapper for Agent Engine execution.
    llm = app.llm(ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), temperature=0))
    # 3. Schemas tell the model which tool it can request and its arguments.
    model_with_tools = llm.bind_tools(app.get_tool_schemas())
    instruction = SystemMessage(content=(
        "You are a pharmacy inventory assistant. Use check_stockout_risk for inventory questions; "
        "do not invent stock levels. CHI is Chicago, OAK is Oak Brook, and DRG-01 is Cefazolin. "
        "Ask for missing identifiers. Report the data source, available units, coverage and risk. "
        "A sample result is synthetic. An error or missing record means risk is unknown. "
        "Never claim a transfer was approved, reserved or delivered by this read-only tool."
    ))

    def call_model(state: MessagesState):
        return {"messages": [model_with_tools.invoke([instruction, *state["messages"]])]}

    def route(state: MessagesState):
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else "done"

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    # 4. Execute through the SDK's wrapped tools, not a direct Python call here.
    graph.add_node("tools", ToolNode(app.get_tools()))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", "done": END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=app.checkpointer())


# Required by the Agent Engine module contract, including when imported.
app.run()
