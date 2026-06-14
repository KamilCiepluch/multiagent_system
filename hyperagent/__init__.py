"""
hyperagent — agent atakujący, który prawdziwie modyfikuje WŁASNY kod Pythona
między rundami (true source-code self-modification, jak w oryginalnym
HyperAgents — w odróżnieniu od `payload_attack/`, gdzie mutowany jest tekstowy
payload, a kod pętli jest stały).

Pojedyncza misja: zaatakować `agents_blocks` przez dany wektor wstrzyknięcia,
osiągając konkretny, weryfikowalny cel (`AttackObjective`). Agent działa w
izolowanym kontenerze Docker i komunikuje się ze światem WYŁĄCZNIE przez
gateway (`hyperagent.gateway`) — to jedyny most do narzędzi ataku, LLM,
ground truth i własnej historii, i jest jedynym miejscem, gdzie cokolwiek
jest bezwarunkowo logowane (mechanizm "niełamliwych adnotacji": agent może
przepisać dosłownie cały swój kod, ale nie może dotknąć ani ominąć gatewaya).

To autoryzowany, białoskrzynkowy benchmark bezpieczeństwa WŁASNEGO systemu
— wszystkie dane są w pełni symulowane (patrz payload_attack/meta_attacker.py
dla identycznego ramowania etycznego).
"""
