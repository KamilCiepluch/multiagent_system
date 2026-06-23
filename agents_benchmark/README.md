# agents_benchmark

Behawioralny benchmark agentów — sprawdza, czy agent **realnie** robi to, co powinien:
odpala właściwe narzędzia, wczytuje właściwe skille i rozpoznaje role. Uruchamia prawdziwego
agenta na modelu, z zadaniem sformułowanym jak zlecenie od supervisora.

## email_agent

```
python -m agents_benchmark.email_agent.run tools     # czy odpala każde narzędzie
python -m agents_benchmark.email_agent.run skills    # czy wczytuje właściwy skill
python -m agents_benchmark.email_agent.run roles     # czy rozpoznaje role
python -m agents_benchmark.email_agent.run all        # wszystko
python -m agents_benchmark.email_agent.run tools --only send_email
```

Przypadki: `email_agent/cases.py`. Każdy przypadek (narzędzie / skill / rola) ma ~5 parafraz tego
samego zlecenia — harness odpala każdą osobno na świeżym świecie i agreguje wynik `X/5`. Dzięki
temu widać odporność systemu na sformułowanie, a nie pojedynczy traf. Kontrolowany świat:
`email_agent/seed.sql` (resetowany przed każdą parafrazą). Wymaga PostgreSQL (agent_benchmark) + Ollama.

Wynik per przypadek: `X/5 PASS`/`FAIL`; dla nieudanych parafraz — czego zabrakło (np. które
narzędzie nie padło) + skrót odpowiedzi modelu. Na końcu zbiorcze `PODSUMOWANIE`: ile przypadków
w pełni zaliczonych, ile pojedynczych przebiegów PASS i rozbicie per przypadek (z oznaczeniem
`<-- do poprawy`).
