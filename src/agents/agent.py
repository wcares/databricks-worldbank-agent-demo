r"""World Bank development insights: four agents in a fixed LangGraph workflow.

    question -> router -> data_analyst (if numbers needed) -> document_researcher (if reports needed) -> writer
                     \-> refuse (off-topic)

- router: an LLM that classifies the question into a plan (needs numbers? needs reports? off-topic?).
- data_analyst: Genie space over the WDI gold tables; returns the SQL it ran and the result table.
- document_researcher: tool-calling agent over the Vector Search index of World Bank report chunks.
- writer: an LLM that writes the answer only from what the two specialists returned, with citations.

Why a fixed workflow and not a free-form supervisor: a langgraph-supervisor version was tested with four
models on Free Edition (Llama 3.3 70B, GPT OSS 120B, Qwen 3.5 122B, Llama 4 Maverick). Every one of them
looped, skipped the report search on "why" questions, ended without an answer, or invented a citation.
Letting code fix the order removes those failure modes. The MLflow ResponsesAgent wrapper follows the
Databricks example notebook "langgraph-multiagent-genie".
"""
import json
import os
import re
from typing import Generator, Optional, TypedDict
from uuid import uuid4

import mlflow
from databricks_langchain import ChatDatabricks, VectorSearchRetrieverTool
from databricks_langchain.genie import GenieAgent
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

############################################
# Configuration (workspace object ids; not secrets)
############################################
# Overridable for model comparisons (test job parameter "llm").
LLM_ENDPOINT_NAME = os.environ.get("WB_AGENT_LLM", "databricks-meta-llama-3-3-70b-instruct")
GENIE_SPACE_ID = "01f1ccf0ce021ae2bbdb20a34b5b1c25"
INDEX_NAME = "wb_demo.gold.doc_chunks_index"

# Free Edition pay-per-token endpoints have a low workspace QPS limit; one question makes several
# model calls, so 429s are retried with the OpenAI client's exponential backoff.
llm = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME, temperature=0, max_retries=8, timeout=120)

REFUSAL = ("I only answer questions about World Bank development data: country economies, poverty, energy, "
           "climate, health, education and related topics.")

############################################
# Specialist agents
############################################
genie = GenieAgent(
    genie_space_id=GENIE_SPACE_ID,
    genie_agent_name="data_analyst",
    description="World Bank WDI indicators for 20 countries, 2000 onward.",
)

report_search = VectorSearchRetrieverTool(
    index_name=INDEX_NAME,
    num_results=5,
    columns=["chunk_id", "title", "doc_type", "doc_year", "country_iso3", "page_start", "page_end",
             "landing_url", "chunk_text"],
    doc_uri="landing_url",
    primary_key="chunk_id",
    dynamic_filter=True,
    tool_name="search_world_bank_reports",
    tool_description=(
        "Searches World Bank country reports (Country Economic Memoranda, Poverty Assessments, Country "
        "Climate and Development Reports, Systematic Country Diagnostics) for 19 countries. Filter on "
        "country_iso3 (ISO3 code such as KEN, IND, BRA) whenever the question names a country."
    ),
)

researcher = create_agent(
    llm,
    tools=[report_search],
    name="document_researcher",
    system_prompt=(
        "You answer questions using World Bank country reports. Call search_world_bank_reports once per "
        "country named in the question, filtering on country_iso3 only (never filter on other columns). "
        "Answer only from the passages returned. "
        "For every claim, cite the report title, its year and the page range, and give its landing_url. "
        "If the passages do not answer the question, say so plainly."
    ),
)


############################################
# Workflow
############################################
class State(TypedDict, total=False):
    messages: list
    question: str
    plan: dict
    data_result: str
    data_sql: str
    report_result: str


ROUTER_PROMPT = """Classify the user's question about country development. Reply with JSON only:
{"off_topic": bool, "needs_data": bool, "needs_reports": bool}

needs_data: the answer needs numbers from World Bank indicators (GDP, poverty rate, electricity access, CO2,
  life expectancy, population, school enrollment, mortality, renewables, unemployment, exports, health
  spending, internet use, inflation), for example levels, trends, comparisons or rankings.
needs_reports: the question asks why, asks for causes, drivers, constraints, policies or explanations, or
  asks what the World Bank or its reports say.
off_topic: the question is not about country development, economics, poverty, energy, climate, health or
  education."""

WHY_WORDS = re.compile(r"\b(why|explain|cause|driver|constraint|polic|what does the world bank|report|say)", re.I)


def parse_plan(text: str, question: str) -> dict:
    """Plan from the router's JSON; fall back to keyword rules if the model did not return valid JSON."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        plan = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        plan = {}
    plan = {k: bool(plan.get(k, False)) for k in ("off_topic", "needs_data", "needs_reports")}
    if WHY_WORDS.search(question):
        plan["needs_reports"] = True  # a "why" question always gets the reports, whatever the model said
    if not plan["off_topic"] and not (plan["needs_data"] or plan["needs_reports"]):
        plan["needs_data"] = plan["needs_reports"] = True
    return plan


def router(state: State) -> State:
    question = state["question"]
    reply = llm.invoke([SystemMessage(ROUTER_PROMPT), HumanMessage(question)])
    plan = parse_plan(reply.content if isinstance(reply.content, str) else "", question)
    return {"plan": plan, "messages": [AIMessage(content=f"Plan: {json.dumps(plan)}", name="router")]}


def refuse(state: State) -> State:
    return {"messages": [AIMessage(content=REFUSAL, name="refuse")]}


def data_analyst(state: State) -> State:
    out = genie.invoke({"messages": [{"role": "user", "content": state["question"]}]})
    by_name = {m.name: m.content for m in out.get("messages", []) if getattr(m, "name", None)}
    result = by_name.get("query_result", "") or "Genie returned no result."
    return {"data_result": result, "data_sql": by_name.get("query_sql", ""),
            "messages": [AIMessage(content=result, name="data_analyst")]}


def document_researcher(state: State) -> State:
    try:
        out = researcher.invoke({"messages": [HumanMessage(state["question"])]})
    except Exception as first_error:  # seen in testing: the model wrote an invalid filter ("doc_year >=")
        try:
            hits = report_search.invoke({"query": state["question"]})
            out = {"messages": [AIMessage(content=f"Passages found (no filter):\n{hits}")]}
        except Exception:
            msg = f"The report search failed ({type(first_error).__name__}); no report findings are available."
            return {"report_result": msg, "messages": [AIMessage(content=msg, name="document_researcher")]}
    answer = next((m.content for m in reversed(out["messages"])
                   if m.type == "ai" and isinstance(m.content, str) and m.content.strip()), "")
    answer = answer or "The report search returned nothing relevant."
    return {"report_result": answer, "messages": [AIMessage(content=answer, name="document_researcher")]}


WRITER_PROMPT = """You write the final answer for a World Bank development insights assistant.
Use ONLY the material below. Do not add facts, numbers or sources from your own knowledge.
- State each number with its year and unit, rounded to at most 2 decimals, and cite it as "World Bank WDI".
- Cite report content with the report title, year, pages and link exactly as given.
- If a part of the question is not covered by the material, say so plainly.
Write a short, clear answer in prose (a small table is fine for comparisons)."""


def writer(state: State) -> State:
    parts = [f"Question: {state['question']}"]
    if state.get("data_result"):
        parts.append(f"Indicator data (World Bank WDI, query: {state.get('data_sql', '')}):\n{state['data_result']}")
    if state.get("report_result"):
        parts.append(f"Findings from World Bank reports:\n{state['report_result']}")
    reply = llm.invoke([SystemMessage(WRITER_PROMPT), HumanMessage("\n\n".join(parts))])
    text = reply.content if isinstance(reply.content, str) else ""
    text = text.strip() or state.get("report_result") or state.get("data_result", "")
    return {"messages": [AIMessage(content=text, name="writer")]}


def after_router(state: State) -> str:
    plan = state["plan"]
    if plan["off_topic"]:
        return "refuse"
    return "data_analyst" if plan["needs_data"] else "document_researcher"


def after_data(state: State) -> str:
    return "document_researcher" if state["plan"]["needs_reports"] else "writer"


graph = StateGraph(State)
graph.add_node("router", router)
graph.add_node("refuse", refuse)
graph.add_node("data_analyst", data_analyst)
graph.add_node("document_researcher", document_researcher)
graph.add_node("writer", writer)
graph.add_edge(START, "router")
graph.add_conditional_edges("router", after_router, ["refuse", "data_analyst", "document_researcher"])
graph.add_conditional_edges("data_analyst", after_data, ["document_researcher", "writer"])
graph.add_edge("document_researcher", "writer")
graph.add_edge("refuse", END)
graph.add_edge("writer", END)
workflow = graph.compile()


############################################
# MLflow ResponsesAgent wrapper
############################################
class WorldBankAgent(ResponsesAgent):
    """Streams one output item per workflow step: a <name>step</name> marker, then that step's message."""

    def __init__(self, app):
        self.app = app

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        outputs = [e.item for e in self.predict_stream(request) if e.type == "response.output_item.done"]
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)

    def predict_stream(self, request: ResponsesAgentRequest) -> Generator[ResponsesAgentStreamEvent, None, None]:
        msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        question = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
        if isinstance(question, list):  # content parts
            question = " ".join(p.get("text", "") for p in question if isinstance(p, dict))
        for update in self.app.stream({"question": question, "messages": []}, stream_mode="updates"):
            for node, delta in update.items():
                yield ResponsesAgentStreamEvent(
                    type="response.output_item.done",
                    item=self.create_text_output_item(text=f"<name>{node}</name>", id=str(uuid4())),
                )
                new = (delta or {}).get("messages", [])
                if new:
                    yield from output_to_responses_items_stream(new)


mlflow.langchain.autolog()
AGENT = WorldBankAgent(workflow)
mlflow.models.set_model(AGENT)
