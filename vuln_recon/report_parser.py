"""
Parser raportów Garak (JSONL) → czyste modele `Finding` / `Hit`.

Czyste funkcje (bez DB, bez importu garaka) — testowalne na fixturze stringa.

Format zweryfikowany na garak 0.15.1:
  • <prefix>.report.jsonl — strumień wpisów; interesują nas `entry_type == "eval"`:
        {"entry_type":"eval","probe":"dan.DanInTheWild","detector":"...","passed":N,
         "fails":M,"nones":K,"total_evaluated":T,...}
    → jeden Finding na (probe, detector); failure_rate = fails/total_evaluated.
  • <prefix>.hitlog.jsonl — pojedyncze trafienia (próby, które złamały model). Pola bywają
    zależne od wersji, więc czytamy defensywnie (.get + normalizacja prompt/output do tekstu).
"""

from __future__ import annotations

import json

from vuln_recon.models import Finding, Hit


def _iter_json_lines(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue  # garak bywa dopisuje nie-JSON (np. progress) — pomijamy


def _as_text(value) -> str | None:
    """Normalizuje prompt/output do tekstu. Garak trzyma prompt jako Turn/Message, np.
    {"role":"user","content":{"text":"...","lang":"en",...}} — wchodzimy rekurencyjnie
    w content/text, żeby wydobyć czysty payload zamiast surowego JSON-a."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "output", "message"):
            if key in value:
                text = _as_text(value[key])
                if text:
                    return text
        if isinstance(value.get("turns"), list):
            return " ".join(_as_text(t) or "" for t in value["turns"]).strip()
    if isinstance(value, list):
        return " ".join(_as_text(v) or "" for v in value).strip()
    return json.dumps(value, ensure_ascii=False, default=str)


def parse_report(text: str) -> list[Finding]:
    """Wyciąga findingi (wpisy `eval`) z treści <prefix>.report.jsonl."""
    findings: list[Finding] = []
    for obj in _iter_json_lines(text):
        if obj.get("entry_type") != "eval":
            continue
        total = obj.get("total_evaluated", obj.get("total", 0)) or 0
        findings.append(Finding(
            probe=obj.get("probe", ""),
            detector=obj.get("detector", ""),
            passed=int(obj.get("passed", 0) or 0),
            total=int(total),
            fails=(int(obj["fails"]) if obj.get("fails") is not None else None),
        ))
    return findings


def parse_hitlog(text: str) -> list[Hit]:
    """Wyciąga trafienia z treści <prefix>.hitlog.jsonl (każda linia = jedno trafienie)."""
    hits: list[Hit] = []
    for obj in _iter_json_lines(text):
        # hitlog nie ma entry_type — każda linia to trafienie; ale gdyby parser dostał
        # report.jsonl, pomijamy wpisy z entry_type (to nie są trafienia).
        if "entry_type" in obj:
            continue
        score = obj.get("score")
        hits.append(Hit(
            probe=obj.get("probe", ""),
            detector=obj.get("detector"),
            prompt=_as_text(obj.get("prompt")),
            output=_as_text(obj.get("output")),
            score=(float(score) if isinstance(score, (int, float)) else None),
        ))
    return hits


def parse_report_file(path: str) -> list[Finding]:
    with open(path, encoding="utf-8") as f:
        return parse_report(f.read())


def parse_hitlog_file(path: str) -> list[Hit]:
    with open(path, encoding="utf-8") as f:
        return parse_hitlog(f.read())
