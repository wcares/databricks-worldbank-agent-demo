"""World Bank development insights: a supervisor over two specialist agents.

- data_analyst: Genie space over the WDI gold tables (numbers, trends, rankings).
- document_researcher: retrieval over World Bank report chunks (explanations, causes, policy).
- supervisor: routes each question, combines answers, cites sources, refuses off-topic requests.

Structure follows the Databricks example notebook "langgraph-multiagent-genie"
(LangGraph supervisor wrapped as an MLflow ResponsesAgent).
"""
from typing import Generator
from uuid import uuid4

import mlflow
from databricks_langchain import ChatDatabricks, VectorSearchRetrieverTool
from databricks_langchain.genie import GenieAgent
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph_supervisor import create_supervisor
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
LLM_ENDPOINT_NAME = "databricks-meta-llama-3-3-70b-instruct"
GENIE_SPACE_ID = "01f1ccf0ce021ae2bbdb20a34b5b1c25"
INDEX_NAME = "wb_demo.gold.doc_chunks_index"
# Upper bound on supervisor/agent steps per question; stops hand-off loops (seen in testing).
RECURSION_LIMIT = 20

# Free Edition pay-per-token endpoints have a low workspace QPS limit; one question makes several
# model calls, so 429s are retried with the OpenAI client's exponential backoff.
llm = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME, temperature=0, max_retries=8, timeout=120)

############################################
# Specialist agents
############################################
data_analyst = GenieAgent(
    genie_space_id=GENIE_SPACE_ID,
    genie_agent_name="data_analyst",
    description=(
        "Answers numeric questions from World Bank World Development Indicators for 20 countries, "
        "2000 onward: GDP per capita and growth, poverty, electricity access, CO2 per capita, life "
        "expectancy, school enrollment, population, under-5 mortality, renewables, unemployment, "
        "exports, health spending, internet use, inflation. Use it for any number, trend, comparison "
        "or ranking."
    ),
)
data_analyst.name = "data_analyst"

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

document_researcher = create_agent(
    llm,
    tools=[report_search],
    name="document_researcher",
    system_prompt=(
        "You answer questions using World Bank country reports. Always call search_world_bank_reports, "
        "filtering on country_iso3 when a country is named. Answer only from the passages returned. "
        "For every claim, cite the report title, its year and the page range, and give its landing_url. "
        "If the passages do not answer the question, say so plainly."
    ),
)

############################################
# Supervisor
############################################
SUPERVISOR_PROMPT = """You are the supervisor of a World Bank development insights assistant.

Agents you can call:
- data_analyst: numbers from World Bank indicator tables (levels, trends, comparisons, rankings).
- document_researcher: explanations, causes and policy discussion from World Bank country reports.

How to work:
1. Decide what the user's latest question needs: numbers, explanation, or both.
2. Call data_analyst for numbers. You MUST call document_researcher whenever the question asks why,
   asks for causes, drivers, constraints or policies, or asks what the World Bank or its reports say.
   A question with both a number and a "why" needs both agents; never explain causes from your own knowledge.
3. Write one answer. State every number with its year and unit. Cite sources: "World Bank WDI" for
   numbers, and the report title, year, pages and link for report content.
4. Call each agent at most once per question. When the agents have replied, write the final answer
   yourself and stop; do not call an agent again to improve an answer.
   Your last message must always be the complete answer in plain prose for the user, never empty.
5. Never invent numbers or citations. If an agent finds nothing, say what is missing.
6. If the question is not about country development, economics, poverty, energy, climate, health or
   education, reply that you only answer questions about World Bank development data, and call no agent.
"""

supervisor = create_supervisor(
    agents=[data_analyst, document_researcher],
    model=llm,
    prompt=SUPERVISOR_PROMPT,
    add_handoff_messages=False,
    output_mode="full_history",
).compile()


############################################
# MLflow ResponsesAgent wrapper (from the Databricks example)
############################################
class LangGraphResponsesAgent(ResponsesAgent):
    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        outputs = [
            event.item
            for event in self.predict_stream(request)
            if event.type == "response.output_item.done"
        ]
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)

    def predict_stream(self, request: ResponsesAgentRequest) -> Generator[ResponsesAgentStreamEvent, None, None]:
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        try:
            yield from self._stream(cc_msgs)
        except GraphRecursionError:
            yield ResponsesAgentStreamEvent(
                type="response.output_item.done",
                item=self.create_text_output_item(
                    text="I could not complete this answer within the step limit. Please ask a narrower question.",
                    id=str(uuid4()),
                ),
            )

    def _stream(self, cc_msgs) -> Generator[ResponsesAgentStreamEvent, None, None]:
        first_message = True
        seen_ids = set()
        last_answer, answered_last = "", False
        for _, events in self.agent.stream({"messages": cc_msgs}, {"recursion_limit": RECURSION_LIMIT},
                                           stream_mode=["updates"]):
            new_msgs = [msg for v in events.values() for msg in v.get("messages", []) if msg.id not in seen_ids]
            if first_message:
                seen_ids.update(msg.id for msg in new_msgs[: len(cc_msgs)])
                new_msgs = new_msgs[len(cc_msgs):]
                first_message = False
            else:
                seen_ids.update(msg.id for msg in new_msgs)
                node_name = tuple(events.keys())[0]
                yield ResponsesAgentStreamEvent(
                    type="response.output_item.done",
                    item=self.create_text_output_item(text=f"<name>{node_name}</name>", id=str(uuid4())),
                )
            if new_msgs:
                yield from output_to_responses_items_stream(new_msgs)
            for msg in new_msgs:
                text = msg.content if isinstance(msg.content, str) else ""
                if msg.type == "ai" and text.strip() and not getattr(msg, "tool_calls", None):
                    last_answer, answered_last = text, True
                elif msg.type == "ai":
                    answered_last = False
            if not first_message and not new_msgs:
                answered_last = False
        # Seen in testing: the supervisor sometimes ends with an empty message after one specialist
        # answered. Repeat the last real answer so the user never gets an empty reply.
        if not answered_last and last_answer:
            yield ResponsesAgentStreamEvent(
                type="response.output_item.done",
                item=self.create_text_output_item(text=last_answer, id=str(uuid4())),
            )


mlflow.langchain.autolog()
AGENT = LangGraphResponsesAgent(supervisor)
mlflow.models.set_model(AGENT)
