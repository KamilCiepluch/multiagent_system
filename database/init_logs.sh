#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE agent_logs;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d agent_logs \
    -f /docker-logs/schema_logs.sql
