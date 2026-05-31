"""
Standalone tester dla TerminalAgent.

Uruchomienie:
    python test_terminal_agent.py

Każda odpowiedź pokazuje kroki: tool calle i ich wyniki,
żeby było widać jak agent dochodzi do odpowiedzi.
"""

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_ollama import ChatOllama

from config import settings
from mcp.server import MCPServer
from mcp.client import build_langchain_tools
from agents.terminal_agent import TerminalAgent

SEP = "─" * 60


def print_step(msg):
    if isinstance(msg, AIMessage):
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = ", ".join(f"{k}={repr(v)}" for k, v in tc["args"].items())
                print(f"  [tool call]  {tc['name']}({args})")
        elif msg.content:
            print(f"  [thinking]   {msg.content[:200]}")

    elif isinstance(msg, ToolMessage):
        preview = str(msg.content)[:300]
        if len(str(msg.content)) > 300:
            preview += "..."
        print(f"  [tool result] {preview}")


def run(agent: TerminalAgent, task: str):
    print(f"\nTask: {task}")
    print(SEP)

    result = agent._agent.stream({"messages": [HumanMessage(content=task)]})

    final = ""
    for chunk in result:
        for _, node_output in chunk.items():
            for msg in node_output.get("messages", []):
                print_step(msg)
                if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                    final = msg.content

    print(SEP)
    print(f"Odpowiedź: {final}")
    print()


def main():
    print(SEP)
    print("  TerminalAgent — standalone tester")
    print(f"  Model: {settings.ollama_model}")
    print(f"  Baza:  {settings.db_name}@{settings.db_host}")
    print(SEP)
    print("  Wpisz zadanie. Wyjście: quit lub Ctrl+C")
    print(SEP)
    print()

    llm = ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url)
    mcp_server = MCPServer()
    mcp_tools = build_langchain_tools(mcp_server)
    agent = TerminalAgent(llm, mcp_tools)

    while True:
        try:
            task = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDo zobaczenia!")
            break

        if not task:
            continue
        if task.lower() in ("quit", "exit"):
            print("Do zobaczenia!")
            break

        run(agent, task)


if __name__ == "__main__":
    main()
