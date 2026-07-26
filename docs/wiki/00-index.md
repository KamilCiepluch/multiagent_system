# agents_blocks — Wiki (hub)

> Pojedyncze źródło prawdy o systemie: co mamy, co potrafi, na czym i jak testowaliśmy, z jakimi
> wynikami. Otwórz `docs/wiki` jako vault Obsidiana → Graph view spina wszystko linkami.
> Materiał do `/wiki:ingest` (LLMWiki, topic `agents-blocks`).

## System (target)
- [[01-agent-system]] — czym jest runtime agentowy: tryby, agenci, narzędzia MCP, SkillGate, config, DB. **Zacznij tu.**
- [[04-system-security-model]] — **mocny check obrony**: co deterministyczne (kod) vs osąd modelu (prompt), przepływy, drabina ablacji „jak uprościć żeby złamać".
- [[02-repo-map]] — mapa repo: co graduuje na master, a co zostaje w labie (+ backup na experiment).

## Jak mierzymy + wyniki
- [[03-benchmark-results]] — wewnętrzny benchmark zachowań (`agents_benchmark/`): zdolności per-agent + e2e, najnowsze snapshoty.
- [[05-attack-experiments]] — **log realnych ataków na system** (wyłomy). E1: role-forge plain-text łamie terminal_agent 83%.
- [[model-vulns/_index|Model Vulnerability Lab]] — podatność samych MODELI na jailbreaki/prompt-injection (rig `test llms`): ranking, powierzchnie ataku, udane ataki, jak odpalić.

## Główne wnioski (skrót)
1. **Chat-safe / agent-dangerous** — modele cenzurowane bronią rozmowy (~1–3% ASR), ale pękają
   agentowo (AgentDojo do 57%, AgentHarm 64%). → atakuj SYSTEM, nie prompt. ([[model-vulns/attack-surfaces|graf]])
2. **Format = jakość** — w naszym e2e większość porażek qwena to brak structured output, nie złe zachowanie.
3. **Obrona na treści/roli, nie na stylu** — na powierzchniach agentowych agents_blocks obfuskacja szkodzi; bramki są na roli nadawcy i ścieżce pliku.

## Konwencje
Notatki numerowane `NN-*` = ścieżka główna; klastry tematyczne w podfolderach (`model-vulns/`).
Linkuj `[[nazwa-pliku]]`. Agregaty tak, surowe prompty SORRY-Bench NIE (licencja — patrz [[model-vulns/how-to-run]]).
