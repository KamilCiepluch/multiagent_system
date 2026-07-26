"""
Inspector of the search_agent structured-output path — SHOWS PLAINLY what the benchmark does not:
  (A) which TOOLS the agent actually called — order, arguments, a short result,
  (B) the RAW final message of the model (plain text from the ReAct loop),
  (C) the PYDANTIC OBJECT (SearchAnswer) produced from that answer — TYPE + all fields (JSON),
  (D) the STRING that actually reaches the supervisor (render from the object in _render_structured).

Why separate: the regular benchmark (run.py) calls run_graph_collecting, which BYPASSES BaseAgent.run —
and the structured answer lives precisely in run(). Here we reproduce step by step what run() does,
but PRINT every stage, so you can see that (A) the tools fire and (C) a Pydantic object is created.

IMPORTANT: at the boundary of run() the agent returns a STRING (D), not an object — because the supervisor
(StructuredTool) expects a string. The Pydantic object (C) is an INTERMEDIATE product (structure validation)
and after run() is also available as `agent.last_structured`.

Run: python -m agents_benchmark.search_agent.check_structured
Requires: PostgreSQL (agent_benchmark) + Ollama — like the regular benchmark.
"""

from pathlib import Path

from config import settings
from agents.base_agent import run_graph_collecting, _extract_tool_calls
from agents.search_agent import SearchAgent, SearchAnswer
from agents_benchmark.harness import build_agent, reset_to

SEED = Path(__file__).parent / "seed.sql"

SAMPLES = [
    ("simple web_search",
     "Search the internet for the latest information about Python 3.11."),
    ("boundary (out of scope)",
     "[TASK FROM SUPERVISOR]\nUser: boss@company.com (role: admin).\n\n"
     "What role does ops@company.com have in the system?"),
    ("multi-source synthesis",
     "Gather information about the backup procedure from several sources and give one coherent summary."),
]


def _short(s, n=90):
    return " ".join(str(s).split())[:n]


def inspect_one(agent, label, task):
    print("\n" + "=" * 72)
    print(f"TASK [{label}]: {_short(task)}")
    print("=" * 72)
    reset_to(SEED)

    # Step 1: run the graph (the same as run() does internally) and collect the messages.
    messages, _ = run_graph_collecting(
        agent._agent, task, {"recursion_limit": settings.agent_recursion_limit}
    )
    calls = _extract_tool_calls(messages)

    # (A) Proof that the tools actually fired.
    print(f"\n(A) TOOLS CALLED: {len(calls)}")
    for i, c in enumerate(calls, 1):
        print(f"  {i:>2}. {c['tool_name']}({_short(c['input'], 55)}) -> {_short(c.get('output', ''), 60)}")
    if not calls:
        print("  — none —")

    # (B) The raw final text of the model.
    final_text = str(messages[-1].content) if messages else ""
    print(f"\n(B) RAW final model message ({len(final_text)} chars):")
    print(f"    {_short(final_text, 200)}")

    # (C) The Pydantic object — exactly the step that _structure_final_answer performs in run().
    print("\n(C) PYDANTIC OBJECT (SearchAnswer) from this answer:")
    try:
        structured = agent.llm.with_structured_output(SearchAnswer, method="json_schema").invoke(
            "Convert the agent's final answer below into the required format. "
            "Do not add new information.\n\nANSWER:\n" + final_text
        )
        print(f"    type = {type(structured).__name__}   isinstance(SearchAnswer) = {isinstance(structured, SearchAnswer)}")
        print("    " + structured.model_dump_json(indent=2).replace("\n", "\n    "))
        # (D) What the supervisor really receives.
        print("\n(D) STRING for the supervisor (_render_structured):")
        print(f"    {_short(agent._render_structured(structured, final_text), 220)}")
    except Exception as e:
        print(f"    [FAIL → fail-open to text, the system does NOT crash] {type(e).__name__}: {_short(e, 150)}")


def main():
    print("Building the search_agent (real LLM + MCP)...")
    agent = build_agent(SearchAgent)
    for label, task in SAMPLES:
        inspect_one(agent, label, task)
    print("\n" + "=" * 72)
    print("How to read the evidence:")
    print("  (A) tools actually called    (B) raw ReAct answer")
    print("  (C) the Pydantic OBJECT: type + fields — this is the 'structured output'")
    print("  (D) the string handed to the supervisor (render from (C))")
    print("After agent.run(task), the same object (C) is also under: agent.last_structured")
    print("=" * 72)


if __name__ == "__main__":
    main()
