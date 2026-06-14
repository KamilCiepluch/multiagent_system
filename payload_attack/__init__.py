"""
payload_attack — silnik ataku „LLM pisze payload" (PAIR-style).

`meta_attacker` generuje i mutuje tekstowe payloady prompt-injection na bazie
historii i werdyktów sędziego; `loop` orkiestruje N iteracji na prawdziwym
systemie docelowym. Zależy wyłącznie od `attack_core`.
"""
