#!/bin/bash
set -e

# Tworzy skonsolidowaną bazę agent_core (schematy: logs / audit / knowledge).
# Zastępuje dawne init_logs.sh + init_audit.sh (agent_logs + agent_audit).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE agent_core;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d agent_core \
    -f /docker-core/schema_core.sql

# Katalog wiedzy (knowledge.attack_techniques) seeduje aplikacja (Python):
#   python -m attack_core.knowledge.seed
