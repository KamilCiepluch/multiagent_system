jak to odpalić?
Jeśli masz plik .env z innymi wartościami, najpierw sprawdź co tam jest i podstaw odpowiednie dane.

Jeśli psql nie jest w PATH (typowe na Windows), masz dwie opcje:

Opcja A — dodaj pełną ścieżkę do psql:
```
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" postgresql://postgres:postgres@localhost:5432/agent_benchmark -f database/schema.sql
```

Opcja B — przez Docker, jeśli baza chodzi w kontenerze:
```
docker exec -i <nazwa_kontenera> psql -U postgres -d agent_benchmark < database/schema.sql
docker exec -i <nazwa_kontenera> psql -U postgres -d agent_benchmark < seeds/seed_data.sql
```