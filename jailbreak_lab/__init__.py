"""Package marker so pure, dependency-free pieces (secret_judge, defenses) can be imported as
`jailbreak_lab.<module>` from elsewhere in the repo. The standalone REPL (`python lab.py` run from
inside this folder) is unaffected — it imports its siblings as top-level modules, not via this package.
"""
