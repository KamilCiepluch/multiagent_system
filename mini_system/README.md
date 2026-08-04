# mini_system — chat agent + search agent over a simulated internet

A deliberately bare agentic system, packed into one folder: world, agents, knowledge-base tooling
and its own observability database. It borrows only the shared runtime from the repo
(`agents/base_agent.py` → `stateful_agent` → `conversation_agent`, `llm_factory`, `config`).

```
user ──► chat_agent (memory)  ──research(query)──►  search_sim_agent  ──► fake_internet (Postgres)
             │                                            │
             └──────────── every turn, invocation and tool call ────────────► mini_system_logs
```

The chat agent decides on its own whether a turn needs a lookup — there is no router and no roles.
That is the point: it exercises the model's own judgement without any infrastructure-security
layer in the way.

## Entry points

```
python -m mini_system.cli                # chat REPL (/new /reset /history /chats /trace /log /exit)
python -m mini_system.cli --no-log       # ...without writing to the log database
python -m mini_system.cli --no-structured  # ...with the search agent answering in plain text
python -m mini_system.search_agent "why does mars look red?"
python -m mini_system.logs_db            # create the log database + schema
python -m mini_system.logs_db --list     # every chat that was logged
python -m mini_system.logs_db --show     # replay the last conversation (or --show <id>)
```

## Chats

One chat at a time, each with its own history and its own row in the log:

```python
system = MiniAgentSystem()               # chat "default"
system.ask("what is the most venomous animal?")
system.new_chat()                        # fresh history, new conversation, turn numbering from 1
system.new_chat("interview-3")           # ...under a name you choose
system.history()                         # the current chat, as the model sees it
```

`/reset` is `new_chat()` under the same name — a new chat rather than a continuation with
amnesia, so the log can never suggest the model saw what it did not.

## Tools and skills

The chat agent has one domain tool, `research`, which is the search agent. Skills (procedures and
policies from `agent_skills`) are **supported** by both agents — they carry `list_skills` /
`load_skill` behind the same before-agent gate the task agents use — but neither agent has any
yet, so the catalog is empty and the gate injects nothing. Adding a row for `chat_agent` or
`search_sim_agent` is all it takes; skill calls are logged like any other tool call. One
difference from `agents/skill_gate.py`: here an unreachable skills database reads as "no skills"
rather than ending the turn, because the mini system is meant to run on its own (`skills.py`).

Knowledge-base tooling:

```
python -m mini_system.internet_db        # create + seed the world (idempotent)
python -m mini_system.kb_add             # type pages in by hand, embedded on save
python -m mini_system.kb_studio          # generate pages with a model, console, human-in-the-loop
python -m mini_system.kb_studio_gui      # ...the same as a GUI with editable cards
python -m mini_system.kb_viewer          # browse the world as a self-contained HTML page
python -m mini_system.kb_backup dump data/kb/world.json     # snapshot / restore / merge
python -m mini_system.canary_hazards     # load the inert hazard canaries
```

## Adding pages by hand (`kb_add`)

An interactive console for writing pages yourself — the manual counterpart to `kb_studio`, which
generates them with a model. Every saved page is embedded on write (nomic-embed-text 768d + FTS),
so it is searchable the instant you save it; nothing is written without confirmation.

```
python -m mini_system.kb_add                            # asks which database to fill
python -m mini_system.kb_add --db fake_internet_realism # target a specific database
```

Per page it asks: **category → topic slug → title → content → sensitive?**, shows the entry, then
`[s]ave / [e]dit / [n]skip / [q]uit`, and loops to the next one.

- **Choose the target database first.** Defaults to the working world (`fake_internet`); point it
  at a separate database (e.g. an experiment base) to keep test material out of the world the
  agent normally searches.
- **Multi-line content.** Type as many lines as you like; finish with a single line containing
  only `.` — the lines are joined into one paragraph, like the rest of the corpus.
- **`sensitive?` has a sensible default** derived from the category (`drugs`, `suicide`, … default
  to yes), which you can override per page.
- **Embedded and verified on save.** After writing, it searches for the page by its title and
  prints the top hit with its match tag (`[kw+sem]`), so a dead embedding model is visible
  immediately rather than silently producing un-searchable pages.
- **Re-adding an existing `(category, topic)` updates it** — the console says `updated` instead of
  `saved` and recomputes the embedding.

After a session: `python -m mini_system.kb_viewer` to browse, or
`python -m mini_system.kb_backup dump data/kb/<name>.json` to snapshot the version.

## Databases

| database | what lives there |
|---|---|
| `fake_internet` | the world: `pages(category, topic, title, content, is_sensitive, embedding, fts)` |
| `mini_system_logs` | observability: `conversations → turns → agent_invocations → tool_calls`, plus `messages` (per invocation) |

Both are created on demand and are independent of the big system's `agent_core`.

## How retrieval works

Hybrid: Postgres full-text search (exact lexemes, the only channel that reliably finds rare or
invented tokens) fused with pgvector cosine similarity over `nomic-embed-text` embeddings (the
only channel that finds paraphrases), combined by Reciprocal Rank Fusion. Cutoffs are measured,
not guessed. Full write-up, including the failure modes each guard exists for:
`docs/wiki/07-research-agent-toolkit.md`.

## How logging works

`observability.py` wraps the tools the system hands to its agents, so a tool call is recorded
exactly as it was made and returned — the agent classes themselves are never modified. Three rules
hold throughout:

- **Nothing is reconstructed.** `tool_calls` holds real arguments and real results; `messages`
  holds what each model actually produced, tied to the invocation that produced it — the chat
  agent's dialogue and the search agent's own run, side by side but never mixed.
- **A tool call is not a model answer.** They are separate rows: `tool_calls` for calls,
  `messages.role` (`ai` / `tool`) for what the model said and what came back.
- **Logging never breaks the chat.** Every write is wrapped; if the log database is unreachable
  the system reports it once and keeps talking, unobserved.

Per user question you therefore get: the question, every agent that ran, in order, what each model
said between calls, every call with its real arguments and result, and the final answer. Replay it
with `python -m mini_system.logs_db --show`, or `/log` inside the REPL:

```
=== turn 1  [ok, 33 ms]
  user> what is the most venomous animal?
    [agent] chat_agent (ok, 27 ms) task='what is the most venomous animal?'
      model> calls research({'query': 'most venomous animal'})
        [agent] search_sim_agent (ok, 12 ms) task='most venomous animal'  {'pages_read': [16], 'used_page_ids': [16]}
          model> calls search_internet({'query': 'most venomous animal'})
          tool>  1. search_internet({'query': 'most venomous animal'}) [ok, 120 ms] -> 1. [16] Box Jellyfish [kw+sem]
          model> calls read_page({'page_id': 16})
          tool>  2. read_page({'page_id': 16}) [ok, 30 ms] -> Full page text about the box jellyfish.
          model> Box jellyfish. [sources: 16]
      tool>  1. research({'query': 'most venomous animal'}) [ok, 900 ms] -> Box jellyfish.
      model> The box jellyfish is usually named the most venomous.
  bot>  The box jellyfish is usually named the most venomous.
```

### Which pages the search agent decided to use

Retrieval hands the agent up to five candidates; the answer is what it does with them. That
decision is recorded on the invocation as `structured`:

- `used_page_ids` — what the model declared it based the answer on. The search agent the mini
  system runs answers with `{answer, used_page_ids}` (`StructuredSearchSimAgent`), so this is a
  field, not something to be read out of prose.
- `pages_read` — derived from the `read_page` calls it actually made, so the measurement holds
  even when the model ignores the output schema.

`used_page_ids ⊄ pages_read` is an answer citing pages it never opened. Switch the schema off with
`--no-structured` (or `MiniAgentSystem(structured_search=False)`) — `pages_read` is recorded
either way. Standalone, `SearchSimAgent` keeps its plain-text contract, which is what the
benchmark reads.

### Live tool trace

The REPL prints every call as it happens, nested by agent:

```
you> What is the most venomous animal?
    [agent] chat_agent  <- What is the most venomous animal?
    . research(query='most venomous animal in the world')
      [agent] search_sim_agent  <- most venomous animal in the world
      . search_internet(query='most venomous animal in the world', limit='5')
        -> 1. [16] (Animals/box-jellyfish) Australian Box Jellyfish [kw+sem] …
      -> The title of "most venomous animal" depends on how you measure it …
bot> [search_internet, research] …
```

This is what tells you whether an answer is grounded or invented: `[no tools]` on the answer line
means the model spoke from its own parametric memory and never touched the knowledge base, and
the `read_page` lines show exactly which pages reached the model. Toggle with `/trace`, start
with `--quiet` to switch it off. The trace works even under `--no-log`, and the same data is
available programmatically as `system.recorder.turn_calls` after each turn.
