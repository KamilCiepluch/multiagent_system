"""
vuln_recon — warstwa rozpoznania podatności ATAKOWANEGO modelu narzędziem red-team (Garak).

Garak odpalamy jako SUBPROCESS (`python -m garak ...`), nie importujemy go w kodzie —
dzięki temu ciężka zależność jest opcjonalna (requirements-recon.txt) i odizolowana od
reszty systemu. Wyniki (findingi per probe + konkretne trafienia) lądują w schemacie
`recon` bazy agent_core (database/recon_db.py).

Projekt: docs/garak_recon_design.md
"""
