"""
Testy jednostkowe dla TerminalAgent, SearchAgent i Supervisor.

Obszary:
- TerminalAgent.TOOL_NAMES: terminal + github + repo tools; brak email/search
- SearchAgent.TOOL_NAMES: search tools; brak email/terminal
- Skill tools (list_skills / load_skill) dla TerminalAgent i SearchAgent
- Supervisor: poprawność agent_lines w system prompt, _make_agent_tool,
              narzędzia = agenci (nie skill tools), brak list_skills/load_skill
"""
from unittest.mock import MagicMock, patch

import pytest

from database.models import AgentSkill


# ── helpery ─────────────────────────────────────────────────────────────────

def _skill(name="test-skill", description="Opis", content="Krok 1", agent_name="terminal_agent"):
    return AgentSkill(id=1, agent_name=agent_name, name=name,
                      description=description, content=content, created_at=None)


def _make_terminal_agent():
    from agents.terminal_agent import TerminalAgent
    mock_tools = {name: MagicMock() for name in TerminalAgent.TOOL_NAMES}
    with patch("agents.base_agent.create_agent", return_value=MagicMock()):
        return TerminalAgent(MagicMock(), mock_tools)


def _make_search_agent():
    from agents.search_agent import SearchAgent
    mock_tools = {name: MagicMock() for name in SearchAgent.TOOL_NAMES}
    with patch("agents.base_agent.create_agent", return_value=MagicMock()):
        return SearchAgent(MagicMock(), mock_tools)


class FakeAgent:
    """Minimalny duck-typed agent do testów Supervisora."""
    def __init__(self, name, description):
        self.NAME = name
        self.DESCRIPTION = description

    def run(self, task: str) -> str:
        return f"[{self.NAME}] wykonano: {task}"


# ── TerminalAgent — zakres narzędzi ─────────────────────────────────────────

class TestTerminalAgentScope:
    def test_has_execute_command(self):
        from agents.terminal_agent import TerminalAgent
        assert "execute_command" in TerminalAgent.TOOL_NAMES

    def test_has_all_github_tools(self):
        from agents.terminal_agent import TerminalAgent
        for tool in ("check_github_source", "list_github_sources",
                     "add_github_source", "update_github_source"):
            assert tool in TerminalAgent.TOOL_NAMES, f"Brak narzędzia: {tool}"

    def test_has_all_repo_tools(self):
        from agents.terminal_agent import TerminalAgent
        for tool in ("clone_repo", "build_repo", "list_repos",
                     "list_repo_commands", "uninstall_repo"):
            assert tool in TerminalAgent.TOOL_NAMES, f"Brak narzędzia: {tool}"

    def test_no_email_tools(self):
        from agents.terminal_agent import TerminalAgent
        for tool in ("list_emails", "send_email", "read_email", "reply_email",
                     "forward_email", "delete_email", "check_email_contact", "classify_email"):
            assert tool not in TerminalAgent.TOOL_NAMES, f"Niedozwolone narzędzie: {tool}"

    def test_no_search_tools(self):
        from agents.terminal_agent import TerminalAgent
        for tool in ("web_search", "search_internal", "search_external",
                     "list_search_sources", "search_source"):
            assert tool not in TerminalAgent.TOOL_NAMES, f"Niedozwolone narzędzie: {tool}"


# ── SearchAgent — zakres narzędzi ────────────────────────────────────────────

class TestSearchAgentScope:
    def test_has_web_search(self):
        from agents.search_agent import SearchAgent
        assert "web_search" in SearchAgent.TOOL_NAMES

    def test_has_all_search_source_tools(self):
        from agents.search_agent import SearchAgent
        for tool in ("list_search_sources", "check_search_source",
                     "search_source", "search_internal", "search_external"):
            assert tool in SearchAgent.TOOL_NAMES, f"Brak narzędzia: {tool}"

    def test_no_email_tools(self):
        from agents.search_agent import SearchAgent
        for tool in ("list_emails", "send_email", "read_email",
                     "check_email_contact", "classify_email"):
            assert tool not in SearchAgent.TOOL_NAMES, f"Niedozwolone narzędzie: {tool}"

    def test_no_terminal_tools(self):
        from agents.search_agent import SearchAgent
        for tool in ("execute_command", "clone_repo", "build_repo",
                     "check_github_source", "uninstall_repo"):
            assert tool not in SearchAgent.TOOL_NAMES, f"Niedozwolone narzędzie: {tool}"


# ── TerminalAgent — skill tools ──────────────────────────────────────────────

class TestTerminalAgentSkillTools:
    def test_list_skills_calls_db_with_terminal_agent(self):
        skills = [_skill("bezpieczny-git", "Opis A", agent_name="terminal_agent")]
        agent = _make_terminal_agent()
        list_tool = next(t for t in agent.tools if t.name == "list_skills")

        with patch("agents.base_agent.db_list_skills", return_value=skills) as mock_list:
            result = list_tool.func()

        mock_list.assert_called_once_with("terminal_agent")
        assert "bezpieczny-git" in result
        assert "Opis A" in result

    def test_list_skills_empty_returns_info(self):
        agent = _make_terminal_agent()
        list_tool = next(t for t in agent.tools if t.name == "list_skills")
        with patch("agents.base_agent.db_list_skills", return_value=[]):
            result = list_tool.func()
        assert "brak" in result.lower()

    def test_load_skill_returns_content(self):
        skill = _skill("bezpieczny-git", content="Krok 1: sprawdź github_source",
                       agent_name="terminal_agent")
        agent = _make_terminal_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")

        with patch("agents.base_agent.db_get_skill", return_value=skill) as mock_get:
            result = load_tool.func("bezpieczny-git")

        mock_get.assert_called_once_with("bezpieczny-git", "terminal_agent")
        assert "Krok 1: sprawdź github_source" in result

    def test_load_nonexistent_skill_returns_error(self):
        agent = _make_terminal_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")
        with patch("agents.base_agent.db_get_skill", return_value=None):
            result = load_tool.func("nie-ma-czegoś-takiego")
        assert "nie istnieje" in result.lower() or "niedostępny" in result.lower()

    def test_load_skill_scoped_to_terminal_agent(self):
        """load_skill nie może wczytać skilla innego agenta."""
        agent = _make_terminal_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")
        with patch("agents.base_agent.db_get_skill", return_value=None) as mock_get:
            load_tool.func("email-skill")
        mock_get.assert_called_once_with("email-skill", "terminal_agent")


# ── SearchAgent — skill tools ─────────────────────────────────────────────────

class TestSearchAgentSkillTools:
    def test_list_skills_calls_db_with_search_agent(self):
        skills = [_skill("wyszukiwanie-wieloźródłowe", "Wieloźródłowe",
                         agent_name="search_agent")]
        agent = _make_search_agent()
        list_tool = next(t for t in agent.tools if t.name == "list_skills")

        with patch("agents.base_agent.db_list_skills", return_value=skills) as mock_list:
            result = list_tool.func()

        mock_list.assert_called_once_with("search_agent")
        assert "wyszukiwanie-wieloźródłowe" in result

    def test_list_skills_empty_returns_info(self):
        agent = _make_search_agent()
        list_tool = next(t for t in agent.tools if t.name == "list_skills")
        with patch("agents.base_agent.db_list_skills", return_value=[]):
            result = list_tool.func()
        assert "brak" in result.lower()

    def test_load_skill_returns_content(self):
        skill = _skill("weryfikacja-źródeł", content="Krok 1: list_search_sources",
                       agent_name="search_agent")
        agent = _make_search_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")

        with patch("agents.base_agent.db_get_skill", return_value=skill) as mock_get:
            result = load_tool.func("weryfikacja-źródeł")

        mock_get.assert_called_once_with("weryfikacja-źródeł", "search_agent")
        assert "Krok 1: list_search_sources" in result

    def test_load_nonexistent_skill_returns_error(self):
        agent = _make_search_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")
        with patch("agents.base_agent.db_get_skill", return_value=None):
            result = load_tool.func("nie-istnieje")
        assert "nie istnieje" in result.lower() or "niedostępny" in result.lower()

    def test_load_skill_scoped_to_search_agent(self):
        """load_skill nie może wczytać skilla innego agenta."""
        agent = _make_search_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")
        with patch("agents.base_agent.db_get_skill", return_value=None) as mock_get:
            load_tool.func("terminal-skill")
        mock_get.assert_called_once_with("terminal-skill", "search_agent")


# ── Supervisor — _make_agent_tool ────────────────────────────────────────────

class TestMakeAgentTool:
    def test_tool_name_equals_agent_name(self):
        from agents.supervisor import _make_agent_tool
        fake = FakeAgent("search_agent", "Wyszukuje informacje")
        tool = _make_agent_tool(fake)
        assert tool.name == "search_agent"

    def test_tool_description_equals_agent_description(self):
        from agents.supervisor import _make_agent_tool
        fake = FakeAgent("terminal_agent", "Wykonuje komendy w terminalu")
        tool = _make_agent_tool(fake)
        assert tool.description == "Wykonuje komendy w terminalu"

    def test_tool_calls_agent_run(self):
        from agents.supervisor import _make_agent_tool
        fake = FakeAgent("email_agent", "Zarządza pocztą")
        tool = _make_agent_tool(fake)
        result = tool.func(task="wyślij email do Alicji")
        assert "email_agent" in result
        assert "wyślij email do Alicji" in result

    def test_tool_has_task_input_schema(self):
        from agents.supervisor import _make_agent_tool, _TaskInput
        fake = FakeAgent("email_agent", "Zarządza pocztą")
        tool = _make_agent_tool(fake)
        assert tool.args_schema is _TaskInput


# ── Supervisor — system prompt i narzędzia ───────────────────────────────────

class TestSupervisorBuild:
    """Weryfikuje że Supervisor poprawnie buduje system prompt i listę narzędzi."""

    def _capture_create_agent_call(self, agents):
        """
        Tworzy Supervisor i przechwytuje argumenty przekazane do create_agent.
        Zwraca (llm, tools, system_prompt).
        """
        captured = {}

        def fake_create(llm, tools, system_prompt=None):
            captured["llm"] = llm
            captured["tools"] = tools
            captured["system_prompt"] = system_prompt
            return MagicMock()

        with patch("agents.supervisor.create_agent", side_effect=fake_create):
            from agents.supervisor import Supervisor
            Supervisor(MagicMock(), agents)

        return captured

    def test_supervisor_name(self):
        from agents.supervisor import Supervisor
        assert Supervisor.NAME == "supervisor"

    def test_system_prompt_contains_all_agent_names(self):
        agents = [
            FakeAgent("email_agent", "Zarządza pocztą"),
            FakeAgent("terminal_agent", "Wykonuje komendy"),
            FakeAgent("search_agent", "Wyszukuje informacje"),
        ]
        captured = self._capture_create_agent_call(agents)
        prompt = captured["system_prompt"]
        for a in agents:
            assert a.NAME in prompt, f"Brak agenta '{a.NAME}' w system prompt"

    def test_system_prompt_contains_all_agent_descriptions(self):
        agents = [
            FakeAgent("email_agent", "Zarządza pocztą"),
            FakeAgent("terminal_agent", "Wykonuje komendy"),
        ]
        captured = self._capture_create_agent_call(agents)
        prompt = captured["system_prompt"]
        assert "Zarządza pocztą" in prompt
        assert "Wykonuje komendy" in prompt

    def test_tools_list_contains_all_agents_by_name(self):
        agents = [
            FakeAgent("email_agent", "Zarządza pocztą"),
            FakeAgent("terminal_agent", "Wykonuje komendy"),
        ]
        captured = self._capture_create_agent_call(agents)
        tool_names = [t.name for t in captured["tools"]]
        assert "email_agent" in tool_names
        assert "terminal_agent" in tool_names

    def test_tools_list_count_equals_agents_count(self):
        agents = [
            FakeAgent("email_agent", "E"),
            FakeAgent("terminal_agent", "T"),
            FakeAgent("search_agent", "S"),
        ]
        captured = self._capture_create_agent_call(agents)
        assert len(captured["tools"]) == len(agents)

    def test_supervisor_has_no_list_skills_tool(self):
        """Supervisor deleguje — nie ma własnych skill tools."""
        agents = [FakeAgent("email_agent", "Zarządza pocztą")]
        captured = self._capture_create_agent_call(agents)
        tool_names = [t.name for t in captured["tools"]]
        assert "list_skills" not in tool_names

    def test_supervisor_has_no_load_skill_tool(self):
        """Supervisor deleguje — nie ma własnych skill tools."""
        agents = [FakeAgent("email_agent", "Zarządza pocztą")]
        captured = self._capture_create_agent_call(agents)
        tool_names = [t.name for t in captured["tools"]]
        assert "load_skill" not in tool_names

    def test_empty_agents_list_gives_empty_tools(self):
        captured = self._capture_create_agent_call([])
        assert captured["tools"] == []

    def test_preamble_in_system_prompt(self):
        """System prompt zaczyna się od preambuły z zasadami delegowania."""
        agents = [FakeAgent("email_agent", "E")]
        captured = self._capture_create_agent_call(agents)
        prompt = captured["system_prompt"]
        assert "supervisor" in prompt.lower() or "deleguj" in prompt.lower()


# ── Testy integracyjne — wymagają działającej bazy (pytest -m integration) ──

@pytest.mark.integration
class TestTerminalAgentSkillIsolation:
    """Weryfikuje izolację skillów terminal_agent na prawdziwej bazie."""

    EXPECTED_SKILLS = {
        "bezpieczny-clone",
        "weryfikacja-github-source",
        "instalacja-repo",
        "obsługa-nieznanego-repo",
    }
    FOREIGN_SKILL = "obsługa-nieznanego-nadawcy"  # należy do email_agent

    def test_list_skills_returns_only_terminal_agent_records(self, no_commit_db):
        from database.db import list_skills
        skills = list_skills("terminal_agent")
        assert skills, "Brak skillów — sprawdź seed terminal_agent.sql"
        for skill in skills:
            assert skill.agent_name == "terminal_agent"

    def test_terminal_agent_cannot_load_email_agent_skill(self, no_commit_db):
        from database.db import get_skill
        result = get_skill(self.FOREIGN_SKILL, "terminal_agent")
        assert result is None, (
            f"terminal_agent NIE powinien mieć dostępu do skilla email_agent '{self.FOREIGN_SKILL}'!"
        )

    def test_terminal_agent_can_load_own_skill(self, no_commit_db):
        from database.db import get_skill, list_skills
        skills = list_skills("terminal_agent")
        if not skills:
            pytest.skip("Brak skillów terminal_agent w bazie")
        skill = get_skill(skills[0].name, "terminal_agent")
        assert skill is not None
        assert skill.agent_name == "terminal_agent"
        assert skill.content.strip()

    def test_skill_tool_list_skills_scoped_to_terminal_agent(self, no_commit_db):
        from agents.terminal_agent import TerminalAgent
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            agent = TerminalAgent(MagicMock(), {n: MagicMock() for n in TerminalAgent.TOOL_NAMES})
        list_tool = next(t for t in agent.tools if t.name == "list_skills")
        result = list_tool.func()
        assert self.FOREIGN_SKILL not in result, (
            f"list_skills() ZWRÓCIŁ skill email_agent '{self.FOREIGN_SKILL}' — izolacja naruszna!"
        )

    def test_skill_tool_load_blocks_cross_agent_access(self, no_commit_db):
        from agents.terminal_agent import TerminalAgent
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            agent = TerminalAgent(MagicMock(), {n: MagicMock() for n in TerminalAgent.TOOL_NAMES})
        load_tool = next(t for t in agent.tools if t.name == "load_skill")
        result = load_tool.func(self.FOREIGN_SKILL)
        assert "nie istnieje" in result.lower() or "niedostępny" in result.lower()


@pytest.mark.integration
class TestSearchAgentSkillIsolation:
    """Weryfikuje izolację skillów search_agent na prawdziwej bazie."""

    EXPECTED_SKILLS = {
        "wyszukiwanie-wieloźródłowe",
    }
    FOREIGN_SKILL = "obsługa-nieznanego-nadawcy"  # należy do email_agent

    def test_list_skills_returns_only_search_agent_records(self, no_commit_db):
        from database.db import list_skills
        skills = list_skills("search_agent")
        assert skills, "Brak skillów — sprawdź seed search_agent.sql"
        for skill in skills:
            assert skill.agent_name == "search_agent"

    def test_search_agent_cannot_load_email_agent_skill(self, no_commit_db):
        from database.db import get_skill
        result = get_skill(self.FOREIGN_SKILL, "search_agent")
        assert result is None, (
            f"search_agent NIE powinien mieć dostępu do skilla email_agent '{self.FOREIGN_SKILL}'!"
        )

    def test_search_agent_can_load_own_skill(self, no_commit_db):
        from database.db import get_skill
        result = get_skill("wyszukiwanie-wieloźródłowe", "search_agent")
        assert result is not None, "Skill 'wyszukiwanie-wieloźródłowe' nie istnieje — sprawdź seed"
        assert result.agent_name == "search_agent"
        assert result.content.strip()

    def test_skill_tool_list_skills_scoped_to_search_agent(self, no_commit_db):
        from agents.search_agent import SearchAgent
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            agent = SearchAgent(MagicMock(), {n: MagicMock() for n in SearchAgent.TOOL_NAMES})
        list_tool = next(t for t in agent.tools if t.name == "list_skills")
        result = list_tool.func()
        assert "wyszukiwanie-wieloźródłowe" in result
        assert self.FOREIGN_SKILL not in result, (
            f"list_skills() ZWRÓCIŁ skill email_agent '{self.FOREIGN_SKILL}' — izolacja naruszna!"
        )

    def test_skill_tool_load_blocks_cross_agent_access(self, no_commit_db):
        from agents.search_agent import SearchAgent
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            agent = SearchAgent(MagicMock(), {n: MagicMock() for n in SearchAgent.TOOL_NAMES})
        load_tool = next(t for t in agent.tools if t.name == "load_skill")
        result = load_tool.func(self.FOREIGN_SKILL)
        assert "nie istnieje" in result.lower() or "niedostępny" in result.lower()
