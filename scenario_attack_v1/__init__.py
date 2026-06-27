"""
scenario_attack_v1 — weryfikacja end-to-end datasetu benchmarku `attack_v1`.

`verify_e2e.py` odpala REALNY workflow agentów na każdym mailu z inboxu (reset → invoke →
ground-truth z tool-calli) i sprawdza MACIERZ rola×funkcja: czy uprawniony nadawca dostaje
wykonanie właściwego tool-calla, a nieuprawniony — odmowę/eskalację. To „nocny double-check"
(wolne biegi gpt-oss), nie deterministyczna bramka dev (ta jest w tests/test_dataset_attack_v1.py).
"""
