"""Tests for mini_system: the chat/search wiring, skill support and the recording layer.

Nothing here touches Postgres or a model: the recorder runs with `enabled=False` (it keeps
sequencing and the live trace, it just does not write), `create_agent` is patched out, and the
skills database is patched per test.
"""
from unittest.mock import MagicMock, patch

import pytest

from database.models import AgentSkill


# ── helpers ─────────────────────────────────────────────────────────────────

def _skill(name="topic-block", description="A restriction", content="Do not answer X",
           agent_name="chat_agent"):
    return AgentSkill(id=1, agent_name=agent_name, name=name, description=description,
                      content=content, created_at=None)


def _recorder(**kwargs):
    from mini_system.observability import ConversationRecorder
    return ConversationRecorder("test", "test-model", enabled=False, **kwargs)


def _make_system(**kwargs):
    """MiniAgentSystem with the graph and the world stubbed out."""
    from mini_system.system import MiniAgentSystem
    with patch("agents.base_agent.create_agent", return_value=MagicMock()), \
         patch("mini_system.system.build_internet_tools", return_value={}):
        return MiniAgentSystem(MagicMock(), log=False, **kwargs)


def _msg(kind, **kwargs):
    """A duck-typed message — `_message_row` reads type(msg).__name__, content and tool_calls."""
    cls = type(kind, (), {})
    obj = cls()
    obj.content = kwargs.get("content", "")
    obj.tool_calls = kwargs.get("tool_calls", [])
    obj.tool_call_id = kwargs.get("tool_call_id")
    obj.name = kwargs.get("name")
    return obj


# ── the chat agent: tools, skills, memory ───────────────────────────────────

class TestChatAgentWiring:
    def test_research_is_the_only_domain_tool(self):
        from mini_system.system import ChatWithResearchAgent
        assert ChatWithResearchAgent.TOOL_NAMES == ["research"]

    def test_carries_skill_tools(self):
        """Skills are supported even though the agent has none: the tools are always there."""
        system = _make_system()
        names = {t.name for t in system.chat_agent.tools}
        assert {"research", "list_skills", "load_skill"} <= names

    def test_search_agent_carries_skill_tools_too(self):
        system = _make_system()
        assert {"list_skills", "load_skill"} <= {t.name for t in system.search_agent.tools}

    def test_skill_gate_is_installed(self):
        system = _make_system()
        assert system.chat_agent._build_middleware(), "the chat agent must run the skill gate"

    def test_no_skills_means_an_empty_catalog_not_a_failure(self):
        system = _make_system()
        list_tool = next(t for t in system.chat_agent.tools if t.name == "list_skills")
        with patch("mini_system.skills.db_list_skills", return_value=[]):
            assert "no skills" in list_tool.func(tool_call_id="c1", messages=[]).lower()

    def test_a_skill_shows_up_once_the_agent_has_one(self):
        system = _make_system()
        list_tool = next(t for t in system.chat_agent.tools if t.name == "list_skills")
        with patch("mini_system.skills.db_list_skills", return_value=[_skill()]):
            out = list_tool.func(tool_call_id="c1", messages=[])
        assert "topic-block" in out and "A restriction" in out

    def test_unreachable_skills_database_reads_as_no_skills(self):
        """The skills live in the big system's database; the mini system must survive without it."""
        system = _make_system()
        list_tool = next(t for t in system.chat_agent.tools if t.name == "list_skills")
        with patch("mini_system.skills.db_list_skills", side_effect=RuntimeError("no database")):
            assert "no skills" in list_tool.func(tool_call_id="c1", messages=[]).lower()

    def test_gate_injects_nothing_without_skills(self):
        from mini_system.skills import build_skill_gate
        gate = build_skill_gate("chat_agent")
        with patch("mini_system.skills.db_list_skills", return_value=[]):
            assert gate.before_agent({"messages": []}, None) is None

    def test_gate_injects_the_catalog_when_there_is_one(self):
        from mini_system.skills import build_skill_gate
        gate = build_skill_gate("chat_agent")
        with patch("mini_system.skills.db_list_skills", return_value=[_skill()]):
            injected = gate.before_agent({"messages": []}, None)
        assert [type(m).__name__ for m in injected["messages"]] == ["AIMessage", "ToolMessage"]
        assert "topic-block" in injected["messages"][1].content


# ── starting a new chat ─────────────────────────────────────────────────────

class TestNewChat:
    def test_new_chat_generates_an_id(self):
        system = _make_system()
        first = system.conversation_id
        assert system.new_chat() != first

    def test_new_chat_takes_a_given_id(self):
        system = _make_system()
        assert system.new_chat("interview-3") == "interview-3"
        assert system.conversation_id == "interview-3"

    def test_new_chat_starts_from_an_empty_history(self):
        system = _make_system()
        system.chat_agent.store.save("default", [_msg("HumanMessage", content="hi")])
        system.new_chat()
        assert system.history() == []

    def test_new_chat_restarts_turn_numbering(self):
        system = _make_system()
        system.recorder.start_turn("first question")
        assert system.recorder.turn_index == 1
        system.new_chat()
        assert system.recorder.turn_index == 0

    def test_reset_is_a_new_chat_under_the_same_name(self):
        system = _make_system()
        system.recorder.start_turn("q")
        system.reset()
        assert system.conversation_id == "default"
        assert system.recorder.turn_index == 0
        assert system.history() == []

    def test_switching_away_leaves_the_other_chat_alone(self):
        """Histories live side by side in the store, keyed by conversation id."""
        system = _make_system()
        system.chat_agent.store.save("default", [_msg("HumanMessage", content="hi")])
        system.new_chat("second")
        assert system.history() == []
        assert len(system.chat_agent.history("default")) == 1


# ── the recording layer ─────────────────────────────────────────────────────

class TestRecorder:
    def test_tool_calls_are_attributed_to_the_agent_that_made_them(self):
        rec = _recorder()
        chat_id, chat_token = rec.start_invocation("chat_agent", "task")
        rec.log_tool_call("research", {"query": "q"}, "answer", "ok", None, 5)
        search_id, search_token = rec.start_invocation("search_sim_agent", "q")
        rec.log_tool_call("search_internet", {"query": "q"}, "hits", "ok", None, 3)
        rec.finish_invocation(search_id, search_token, "answer")
        rec.finish_invocation(chat_id, chat_token, "reply")

        assert [(c["agent"], c["tool"]) for c in rec.turn_calls] == [
            ("chat_agent", "research"), ("search_sim_agent", "search_internet")]

    def test_the_search_agent_nests_under_the_chat_agent(self):
        events = []
        rec = _recorder(listener=events.append)
        chat_id, chat_token = rec.start_invocation("chat_agent", "task")
        search_id, search_token = rec.start_invocation("search_sim_agent", "q")
        rec.finish_invocation(search_id, search_token, "a")
        rec.finish_invocation(chat_id, chat_token, "b")
        depths = {e["agent"]: e["depth"] for e in events if e["kind"] == "agent"}
        assert depths["search_sim_agent"] > depths["chat_agent"]

    def test_pages_read_are_derived_from_the_calls_actually_made(self):
        rec = _recorder()
        inv_id, token = rec.start_invocation("search_sim_agent", "q")
        rec.log_tool_call("search_internet", {"query": "q"}, "hits", "ok", None, 1)
        rec.log_tool_call("read_page", {"page_id": 16}, "full text", "ok", None, 1)
        rec.log_tool_call("read_page", {"page_id": "21"}, "full text", "ok", None, 1)
        rec.log_tool_call("read_page", {"page_id": 16}, "full text", "ok", None, 1)  # re-read
        record = rec._retrieval_record(inv_id, {"used_page_ids": [16]})
        rec.finish_invocation(inv_id, token, "answer")
        assert record == {"used_page_ids": [16], "pages_read": [16, 21]}

    def test_retrieval_record_survives_a_model_that_declares_nothing(self):
        rec = _recorder()
        inv_id, token = rec.start_invocation("search_sim_agent", "q")
        rec.log_tool_call("read_page", {"page_id": 3}, "text", "ok", None, 1)
        assert rec._retrieval_record(inv_id, None) == {"pages_read": [3]}
        rec.finish_invocation(inv_id, token, "answer")

    def test_a_failed_read_is_not_counted_as_read(self):
        rec = _recorder()
        inv_id, _ = rec.start_invocation("search_sim_agent", "q")
        rec.log_tool_call("read_page", {"page_id": 9}, None, "error", "boom", 1)
        assert rec._retrieval_record(inv_id, None) is None

    def test_a_message_row_separates_a_model_answer_from_a_tool_call(self):
        from mini_system.observability import _message_row
        ai = _message_row(_msg("AIMessage", content="", tool_calls=[
            {"id": "c1", "name": "research", "args": {"query": "q"}}]), 0)
        result = _message_row(_msg("ToolMessage", content="hits", tool_call_id="c1",
                                   name="research"), 1)
        answer = _message_row(_msg("AIMessage", content="Here it is."), 2)

        assert ai["role"] == "ai" and ai["tool_calls"][0]["name"] == "research"
        assert result["role"] == "tool" and result["tool_name"] == "research"
        assert answer["role"] == "ai" and answer["tool_calls"] is None

    def test_injected_arguments_never_reach_the_log(self):
        from mini_system.observability import loggable_args
        clean = loggable_args({"query": "q", "messages": [object()], "tool_call_id": "c1"})
        assert clean == {"query": "q"}

    def test_logging_off_still_records_the_turn_in_memory(self):
        rec = _recorder()
        assert rec.enabled is False
        rec.start_turn("q")
        inv_id, token = rec.start_invocation("chat_agent", "q")
        rec.log_tool_call("research", {"query": "q"}, "a", "ok", None, 1)
        rec.finish_invocation(inv_id, token, "reply")
        rec.finish_turn("reply")
        assert len(rec.turn_calls) == 1


# ── the search agent's verdict ──────────────────────────────────────────────

class TestSearchAnswer:
    def _agent(self, cls):
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            return cls(MagicMock(), {})

    def test_structured_agent_declares_its_sources(self):
        from mini_system.search_agent import SearchAnswer, StructuredSearchSimAgent
        agent = self._agent(StructuredSearchSimAgent)
        rendered = agent._render_structured(
            SearchAnswer(answer="Box jellyfish.", used_page_ids=[16, 21]), "fallback")
        assert "Box jellyfish." in rendered and "[sources: 16, 21]" in rendered

    def test_no_sources_is_said_out_loud(self):
        from mini_system.search_agent import SearchAnswer, StructuredSearchSimAgent
        agent = self._agent(StructuredSearchSimAgent)
        rendered = agent._render_structured(
            SearchAnswer(answer="Nothing in the knowledge base.", used_page_ids=[]), "fallback")
        assert "[sources: none]" in rendered

    def test_an_empty_answer_falls_back_to_the_raw_text(self):
        from mini_system.search_agent import SearchAnswer, StructuredSearchSimAgent
        agent = self._agent(StructuredSearchSimAgent)
        rendered = agent._render_structured(SearchAnswer(answer="  ", used_page_ids=[]), "raw text")
        assert rendered.startswith("raw text")

    def test_structured_response_can_arrive_as_a_dict(self):
        from mini_system.search_agent import StructuredSearchSimAgent
        agent = self._agent(StructuredSearchSimAgent)
        rendered = agent._render_structured({"answer": "A.", "used_page_ids": [7]}, "fallback")
        assert "[sources: 7]" in rendered

    def test_plain_agent_keeps_the_text_contract(self):
        """The benchmark and the standalone REPL read the last message, so the default stays plain."""
        from mini_system.search_agent import SearchSimAgent
        assert SearchSimAgent.RESPONSE_SCHEMA is None

    def test_the_mini_system_runs_the_structured_one_by_default(self):
        from mini_system.search_agent import StructuredSearchSimAgent
        assert isinstance(_make_system().search_agent, StructuredSearchSimAgent)

    def test_structured_search_can_be_turned_off(self):
        from mini_system.search_agent import StructuredSearchSimAgent
        system = _make_system(structured_search=False)
        assert not isinstance(system.search_agent, StructuredSearchSimAgent)


# ── the research tool: delegation and logging ───────────────────────────────

class TestResearchTool:
    def _tool(self, rec, answer="an answer", messages=None, structured=None, fail=False):
        from mini_system.system import build_research_tool
        agent = MagicMock()
        agent.run_with_messages.side_effect = (
            RuntimeError("model exploded") if fail
            else lambda q: (answer, messages or [], structured))
        return build_research_tool(agent, [], rec), agent

    def test_delegating_opens_an_invocation_for_the_search_agent(self):
        rec = _recorder()
        rec.start_turn("q")
        chat_id, chat_token = rec.start_invocation("chat_agent", "q")
        tool, _ = self._tool(rec, structured={"used_page_ids": [4]})
        assert tool.func("most venomous animal") == "an answer"
        rec.finish_invocation(chat_id, chat_token, "reply")

    def test_a_failed_lookup_is_reported_not_raised(self):
        """A bad generation must not take the conversation down."""
        rec = _recorder()
        rec.start_turn("q")
        chat_id, chat_token = rec.start_invocation("chat_agent", "q")
        tool, _ = self._tool(rec, fail=True)
        assert "research failed" in tool.func("q")
        rec.finish_invocation(chat_id, chat_token, "reply")

    def test_the_query_is_recorded_for_the_caller(self):
        from mini_system.system import build_research_tool
        agent = MagicMock()
        agent.run_with_messages.return_value = ("a", [], None)
        log = []
        build_research_tool(agent, log, None).func("why is mars red")
        assert log == ["why is mars red"]

    def test_it_retries_once_before_giving_up(self):
        from mini_system.system import _run_search
        agent = MagicMock()
        agent.run_with_messages.side_effect = [RuntimeError("500"), ("ok", [], None)]
        assert _run_search(agent, "q")[0] == "ok"
        assert agent.run_with_messages.call_count == 2


# ── the readable log ────────────────────────────────────────────────────────

class TestTimelineRendering:
    def test_model_answers_and_tool_calls_are_told_apart(self):
        """The rendering is the point of the log: who said what, and what was called."""
        from mini_system import logs_db

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [(1, "chat_agent", "most venomous animal?", "ok", 1200, {"pages_read": [16]})],
            [(1, "research", {"query": "most venomous animal"}, "Box jellyfish.", "ok", 900)],
            [("ai", "", [{"name": "research", "args": {"query": "most venomous animal"}}], None),
             ("tool", "Box jellyfish.", None, "research"),
             ("ai", "The box jellyfish.", None, None)],
            [],  # no nested invocations
        ]
        lines = logs_db._invocation_lines(cur, turn_id=1, parent_id=None, indent="  ")
        text = "\n".join(lines)

        assert "[agent] chat_agent" in text
        assert "pages_read" in text
        assert "model> calls research" in text
        assert "tool>  1. research" in text
        assert "model> The box jellyfish." in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
