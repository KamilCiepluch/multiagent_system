"""
Jailbreak Lab — interaktywny REPL do RĘCZNEGO łamania CZYSTYCH modeli.

Idea (żeby nie zapomnieć zapisać ataku): to NARZĘDZIE rozmawia z modelem. Każdy prompt,
który wpiszesz, leci do modelu i jest OD RAZU zalogowany do bazy (jailbreaks.db) z werdyktem
`unknown`. Logowanie jest efektem ubocznym strzału — nie da się o nim zapomnieć. Po zobaczeniu
odpowiedzi tylko dopisujesz ocenę: /win, /partial, /refused, plus opcjonalnie tag/notatkę.

Uruchomienie (środowisko conda `system_agentowy2`):
    python lab.py
    python lab.py --model qwen3.6:27b-ctx8k --session "dan-warmup"

W REPL:
  <cokolwiek bez /> ........ wyślij jako prompt ataku do modelu (i zaloguj)
  /help .................... pełna lista komend
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

import config
from db import VERDICTS, JailbreakDB
from model_client import OllamaClient

HELP = """
KOMENDY:
  (tekst bez /)          wyślij prompt ataku do modelu i zaloguj (werdykt=unknown)
  /help                  ta pomoc
  /quit  /exit           wyjście

  --- ocena ostatniego strzału (albo /win <id>) ---
  /win [id]              werdykt = success  (model się złamał)
  /partial [id]          werdykt = partial  (częściowo uległ)
  /refused [id]          werdykt = refused  (odmówił)
  /verdict [id] <v>      dowolny werdykt: {unknown|success|partial|refused|error}
  /tag [id] <t1,t2>      dopisz tagi
  /note [id] <tekst>     dopisz notatkę

  --- kontekst ataku (ustaw raz, dotyczy kolejnych strzałów) ---
  /goal <tekst>          cel: jakie zachowanie chcesz wywołać
  /technique <etykieta>  technika (DAN, roleplay, prefix-inject, crescendo...)
  /system <prompt>       system prompt modelu (pusto = wyczyść; sam /system = pokaż)
  /temp <float>          temperatura próbkowania
  /param <k> <v>         opcja Ollamy (seed, top_p, num_ctx, ...); /param seed -   usuwa
  /think on|off          osobny kanał myślenia dla modeli rozumujących

  --- model / sesja / rozmowa ---
  /model [nazwa]         przełącz model (bez arg = pokaż aktualny)
  /models                lista zainstalowanych modeli (ollama list)
  /session <nazwa>       etykieta sesji (grupowanie w bazie)
  /multi on|off          tryb multi-turn (utrzymuj historię rozmowy); domyślnie off
  /reset                 nowa rozmowa (czyści historię multi-turn)

  --- podgląd / odtwarzanie ---
  /last                  pokaż ostatni strzał + odpowiedź
  /show <id>             pokaż zapisany atak
  /list [n]              ostatnie n strzałów (domyślnie 15)
  /replay <id> [model]   powtórz zapisany atak (te same wiadomości) na aktualnym/innym modelu
  /stats                 zestawienie werdyktów per model
  /export <plik>         eksport bazy do .json / .csv
""".strip()


class Lab:
    def __init__(self, db: JailbreakDB, client: OllamaClient, *, model: str,
                 temperature: float, session: str | None):
        self.db = db
        self.client = client
        self.model = model
        self.session = session
        # Stan kontekstu ataku — ustawiasz raz, wchodzi do każdego kolejnego logu.
        self.system_prompt: str | None = None
        self.goal: str | None = None
        self.technique: str | None = None
        self.think: bool | None = None
        self.options: dict = {"temperature": temperature}
        # Multi-turn: gdy włączony, trzymamy historię i doklejamy ją do kolejnych strzałów.
        self.multi = False
        self.conversation_id = uuid.uuid4().hex[:12]
        self.history: list[dict[str, str]] = []
        self.turn_index = 0
        self.last_id: int | None = None

    # ---- wysłanie ataku ----------------------------------------------------
    def send(self, prompt: str) -> None:
        # Zbuduj listę wiadomości realnie wysyłaną do modelu (to ona ląduje w logu → repro).
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if self.multi:
            messages.extend(self.history)
        messages.append({"role": "user", "content": prompt})

        try:
            res = self.client.chat(
                messages, model=self.model, options=self.options or None, think=self.think
            )
        except Exception as e:  # log też nieudane strzały (timeout/błąd modelu) — to też dane
            self.last_id = self.db.log_attack(
                model=self.model, messages=messages, response="", session=self.session,
                conversation_id=self.conversation_id, turn_index=self.turn_index,
                base_url=self.client.base_url, options=self.options, system_prompt=self.system_prompt,
                goal=self.goal, technique=self.technique, verdict="error", error=str(e),
            )
            print(f"  [BŁĄD modelu] {e}  (zalogowano #{self.last_id}, werdykt=error)")
            return

        self.last_id = self.db.log_attack(
            model=self.model, messages=messages, response=res.content, session=self.session,
            conversation_id=self.conversation_id, turn_index=self.turn_index,
            base_url=self.client.base_url, options=self.options, system_prompt=self.system_prompt,
            goal=self.goal, technique=self.technique, reasoning=res.reasoning,
            latency_ms=res.latency_ms, eval_count=res.eval_count,
        )
        if self.multi:  # dopisz do historii dopiero po udanej turze
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": res.content})
            self.turn_index += 1

        print()
        if res.reasoning:
            print(f"  \033[90m[thinking] {res.reasoning.strip()[:500]}\033[0m")
        print(res.content.strip() or "(pusta odpowiedź)")
        print(f"\n  \033[36m#{self.last_id}\033[0m  {res.latency_ms} ms"
              f"{f', {res.eval_count} tok' if res.eval_count else ''}"
              f"  -> oceń: /win  /partial  /refused")

    # ---- anotacje ----------------------------------------------------------
    def _target_id(self, arg: str | None) -> int | None:
        if arg and arg.strip().isdigit():
            return int(arg.strip())
        if self.last_id is None:
            print("  (brak strzału do oznaczenia — najpierw coś wyślij albo podaj id)")
        return self.last_id

    def annotate_verdict(self, verdict: str, arg: str | None) -> None:
        aid = self._target_id(arg)
        if aid is None:
            return
        self.db.set_verdict(aid, verdict)
        print(f"  #{aid} -> werdykt = {verdict}")

    # ---- podgląd -----------------------------------------------------------
    def show(self, r: dict) -> None:
        print(f"\n--- atak #{r['id']} -----------------------------------")
        for k in ("ts_utc", "model", "session", "goal", "technique", "verdict", "latency_ms"):
            if r.get(k) not in (None, ""):
                print(f"  {k:<11}: {r[k]}")
        if r.get("tags") and r["tags"] not in ("[]", None):
            print(f"  {'tags':<11}: {', '.join(json.loads(r['tags']))}")
        if r.get("system_prompt"):
            print(f"  {'system':<11}: {r['system_prompt']}")
        print(f"  {'prompt':<11}: {r.get('attack_prompt', '')}")
        if r.get("notes"):
            print(f"  {'notes':<11}: {r['notes']}")
        print(f"  --- odpowiedź ---\n{r.get('response', '') or r.get('error', '')}")
        print("--------------------------------------------------")

    # ---- pętla / dispatch --------------------------------------------------
    def handle(self, line: str) -> bool:
        """Zwraca False, gdy trzeba wyjść."""
        line = line.strip()
        if not line:
            return True
        if not line.startswith("/"):
            self.send(line)
            return True

        parts = line[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            return False
        elif cmd in ("help", "h", "?"):
            print(HELP)
        elif cmd == "win":
            self.annotate_verdict("success", rest)
        elif cmd == "partial":
            self.annotate_verdict("partial", rest)
        elif cmd == "refused":
            self.annotate_verdict("refused", rest)
        elif cmd == "verdict":
            bits = rest.split()
            if bits and bits[0].isdigit():
                aid, v = int(bits[0]), (bits[1] if len(bits) > 1 else "")
            else:
                aid, v = self._target_id(None), (bits[0] if bits else "")
            if v not in VERDICTS:
                print(f"  werdykt musi być z {VERDICTS}")
            elif aid is not None:
                self.db.set_verdict(aid, v); print(f"  #{aid} -> werdykt = {v}")
        elif cmd == "tag":
            bits = rest.split(maxsplit=1)
            if bits and bits[0].isdigit():
                aid, tagstr = int(bits[0]), (bits[1] if len(bits) > 1 else "")
            else:
                aid, tagstr = self._target_id(None), rest
            if aid is not None and tagstr:
                tags = [t.strip() for t in tagstr.replace(",", " ").split() if t.strip()]
                self.db.add_tags(aid, tags); print(f"  #{aid} += tagi {tags}")
        elif cmd == "note":
            bits = rest.split(maxsplit=1)
            if bits and bits[0].isdigit():
                aid, text = int(bits[0]), (bits[1] if len(bits) > 1 else "")
            else:
                aid, text = self._target_id(None), rest
            if aid is not None and text:
                self.db.add_note(aid, text); print(f"  #{aid} += notatka")
        elif cmd == "goal":
            self.goal = rest or None; print(f"  goal = {self.goal!r}")
        elif cmd == "technique":
            self.technique = rest or None; print(f"  technique = {self.technique!r}")
        elif cmd == "system":
            if rest:
                self.system_prompt = rest; print("  system prompt ustawiony")
            elif parts[0:1] == ["system"] and len(parts) == 1:
                print(f"  system = {self.system_prompt!r}")
        elif cmd == "temp":
            try:
                self.options["temperature"] = float(rest); print(f"  temperature = {rest}")
            except ValueError:
                print("  podaj liczbę, np. /temp 0.8")
        elif cmd == "param":
            bits = rest.split()
            if len(bits) >= 2:
                key, val = bits[0], bits[1]
                if val == "-":
                    self.options.pop(key, None); print(f"  usunięto opcję {key}")
                else:
                    try:
                        val_cast: object = int(val)
                    except ValueError:
                        try:
                            val_cast = float(val)
                        except ValueError:
                            val_cast = val
                    self.options[key] = val_cast; print(f"  options[{key}] = {val_cast!r}")
            else:
                print(f"  aktualne options: {self.options}")
        elif cmd == "think":
            self.think = {"on": True, "off": False}.get(rest.lower())
            print(f"  think = {self.think}")
        elif cmd == "model":
            if rest:
                self.model = rest; self.client.model = rest; print(f"  model -> {rest}")
            else:
                print(f"  model = {self.model}")
        elif cmd == "models":
            try:
                for m in self.client.list_models():
                    print(f"  {'* ' if m == self.model else '  '}{m}")
            except Exception as e:
                print(f"  nie mogę pobrać listy modeli: {e}")
        elif cmd == "session":
            self.session = rest or None; print(f"  session = {self.session!r}")
        elif cmd == "multi":
            self.multi = rest.lower() == "on"
            if self.multi:
                self.conversation_id = uuid.uuid4().hex[:12]; self.history = []; self.turn_index = 0
            print(f"  multi-turn = {self.multi}")
        elif cmd == "reset":
            self.conversation_id = uuid.uuid4().hex[:12]; self.history = []; self.turn_index = 0
            print("  nowa rozmowa (historia wyczyszczona)")
        elif cmd == "last":
            r = self.db.get(self.last_id) if self.last_id else self.db.last()
            if r:
                self.show(r)
        elif cmd == "show":
            if rest.isdigit():
                r = self.db.get(int(rest))
                if r:
                    self.show(r)
                else:
                    print(f"  brak ataku #{rest}")
        elif cmd == "list":
            n = int(rest) if rest.isdigit() else 15
            for r in reversed(self.db.list(limit=n)):
                mark = {"success": "S", "partial": "P", "refused": "R",
                        "error": "E", "unknown": "?"}.get(r["verdict"], "?")
                p = (r.get("attack_prompt") or "").replace("\n", " ")[:60]
                print(f"  #{r['id']:<4} [{mark}] {r['model']:<16} {p}")
        elif cmd == "replay":
            bits = rest.split()
            if not bits or not bits[0].isdigit():
                print("  użycie: /replay <id> [model]")
            else:
                self.replay(int(bits[0]), bits[1] if len(bits) > 1 else None)
        elif cmd == "stats":
            rows = self.db.stats()
            if not rows:
                print("  (baza pusta)")
            for r in rows:
                print(f"  {r['model']:<18} total={r['total']:<4} "
                      f"success={r['success'] or 0:<3} partial={r['partial'] or 0:<3} "
                      f"refused={r['refused'] or 0:<3} unknown={r['unknown'] or 0:<3}")
        elif cmd == "export":
            if rest:
                n = self.db.export(rest); print(f"  wyeksportowano {n} wierszy -> {rest}")
            else:
                print("  podaj plik, np. /export dump.json")
        else:
            print(f"  nieznana komenda /{cmd} — /help")
        return True

    def replay(self, attack_id: int, model: str | None) -> None:
        src = self.db.get(attack_id)
        if not src:
            print(f"  brak ataku #{attack_id}")
            return
        messages = json.loads(src["messages"]) if src.get("messages") else []
        target = model or self.model
        try:
            res = self.client.chat(messages, model=target,
                                   options=self.options or None, think=self.think)
        except Exception as e:
            print(f"  [BŁĄD] {e}")
            return
        self.last_id = self.db.log_attack(
            model=target, messages=messages, response=res.content, session=self.session,
            conversation_id=self.conversation_id, replay_of=attack_id, base_url=self.client.base_url,
            options=self.options, system_prompt=src.get("system_prompt"), goal=src.get("goal"),
            technique=src.get("technique"), reasoning=res.reasoning,
            latency_ms=res.latency_ms, eval_count=res.eval_count,
        )
        print(f"\n  [replay #{attack_id} -> {target}]")
        print(res.content.strip() or "(pusta odpowiedź)")
        print(f"\n  \033[36m#{self.last_id}\033[0m  {res.latency_ms} ms  -> oceń: /win /partial /refused")


def _force_utf8_console() -> None:
    """Konsola Windows (cp1250) nie zakoduje odpowiedzi modelu z egzotycznymi znakami i
    wywaliłaby REPL po każdym strzale. Wymuszamy UTF-8 z errors='replace' — nigdy nie crashuje."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def main() -> None:
    _force_utf8_console()
    ap = argparse.ArgumentParser(description="Jailbreak Lab — ręczny REPL do łamania modeli")
    ap.add_argument("--model", default=config.DEFAULT_MODEL)
    ap.add_argument("--base-url", default=config.OLLAMA_BASE_URL)
    ap.add_argument("--temperature", type=float, default=config.DEFAULT_TEMPERATURE)
    ap.add_argument("--session", default=None, help="etykieta sesji (grupowanie w bazie)")
    args = ap.parse_args()

    db = JailbreakDB()
    client = OllamaClient(base_url=args.base_url, model=args.model)
    lab = Lab(db, client, model=args.model, temperature=args.temperature, session=args.session)

    print(f"Jailbreak Lab  |  model={lab.model}  base_url={client.base_url}  "
          f"temp={args.temperature}  session={args.session!r}")
    print("Wpisz prompt = atak (auto-log). /help = komendy. /quit = wyjście.\n")
    while True:
        try:
            line = input("atak> ")
        except (EOFError, KeyboardInterrupt):
            print("\n(koniec)")
            break
        try:
            if not lab.handle(line):
                break
        except Exception as e:  # REPL ma przeżyć każdy błąd komendy
            print(f"  [błąd komendy] {e}")


if __name__ == "__main__":
    main()
