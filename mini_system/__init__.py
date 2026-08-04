"""The mini agent system: a chat agent + a search agent over a simulated internet.

Self-contained on purpose — world (fake_internet), agents, KB authoring tools and its own
observability database all live in this package. It reuses only the shared runtime pieces of
the repo: BaseAgent/StatefulAgent/ConversationAgent, llm_factory and config.

Entry points:
    python -m mini_system.cli             # chat REPL (logs to mini_system_logs)
    python -m mini_system.search_agent    # ask the search agent alone
    python -m mini_system.internet_db     # create + seed the world
    python -m mini_system.kb_studio_gui   # fill the world by hand, with a model's help
    python -m mini_system.kb_viewer       # browse the world as HTML
    python -m mini_system.logs_db --list  # every chat that was logged
    python -m mini_system.logs_db --show  # replay the last conversation as a timeline
"""
