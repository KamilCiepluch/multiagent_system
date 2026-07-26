"""
Jailbreak Lab — GUI (Gradio) nad tym SAMYM backendem co REPL.

Po co: terminal (`input()`) czyta linia-po-linii, więc wklejenie wieloliniowego promptu
rozjeżdża się na kilka osobnych strzałów. Tu jest zwykłe pole tekstowe (textarea) — wklejasz
dowolnie długi, wieloliniowy prompt i idzie jako JEDEN strzał.

Nic tu nie duplikuje logiki: używamy `db.JailbreakDB` i `model_client.OllamaClient` 1:1, więc
wpisy lądują w tej samej bazie `jailbreaks.db` co z REPL — `python db.py stats`, `/replay`,
eksport itd. działają na wspólnych danych.

Uruchomienie (conda `system_agentowy2`):
    python gui.py                      # otworzy http://127.0.0.1:7860
    run_gui.bat                        # to samo na Windowsie
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import gradio as gr

import config
from db import VERDICTS, JailbreakDB
from model_client import OllamaClient

# Singletony — jeden klient i jedna baza na proces (DB otwiera połączenie per-operacja,
# więc bezpiecznie współdzielić). GUI trzyma tylko lekki stan sesji w gr.State.
DB = JailbreakDB()
CLIENT = OllamaClient(base_url=config.OLLAMA_BASE_URL)

_TECH_PATH = Path(__file__).with_name("techniques.json")


def _techniques() -> list[str]:
    try:
        return list(json.loads(_TECH_PATH.read_text(encoding="utf-8"))["techniques"].keys())
    except Exception:
        return []


def _models() -> list[str]:
    try:
        return CLIENT.list_models()
    except Exception:
        return [config.DEFAULT_MODEL]


def fresh_state() -> dict:
    """Nowa rozmowa: świeże conversation_id, pusta historia multi-turn."""
    return {"last_id": None, "conversation_id": uuid.uuid4().hex[:12], "history": [], "turn_index": 0}


# ---- widoki pomocnicze (statystyki + ostatnie strzały) --------------------
def _stats_md() -> str:
    rows = DB.stats()
    if not rows:
        return "_(baza pusta — brak strzałów)_"
    head = "| model | total | ✅ success | 🟡 partial | ❌ refused | ? unknown | err |\n"
    head += "|---|--:|--:|--:|--:|--:|--:|\n"
    body = "\n".join(
        f"| `{r['model']}` | {r['total']} | {r['success'] or 0} | {r['partial'] or 0} "
        f"| {r['refused'] or 0} | {r['unknown'] or 0} | {r['errors'] or 0} |"
        for r in rows
    )
    return head + body


def _recent_rows(limit: int = 15) -> list[list]:
    out = []
    for r in DB.list(limit=limit):
        p = (r.get("attack_prompt") or "").replace("\n", " ")
        if len(p) > 80:
            p = p[:77] + "..."
        out.append([r["id"], r["model"], r["verdict"], p])
    return out


# ---- akcje ----------------------------------------------------------------
def send(prompt, model, session, goal, technique, system_prompt, temperature, multi, think, st):
    """Wyślij prompt do modelu i ZALOGUJ (efekt uboczny — nic nie ginie), jak w REPL."""
    prompt = (prompt or "").strip()
    if not prompt:
        return "", "", "⚠️ Pusty prompt — nic nie wysłano.", st, _stats_md(), _recent_rows()

    messages: list[dict[str, str]] = []
    sysp = (system_prompt or "").strip()
    if sysp:
        messages.append({"role": "system", "content": sysp})
    if multi and st.get("history"):
        messages.extend(st["history"])
    messages.append({"role": "user", "content": prompt})

    options = {"temperature": float(temperature)}
    think_flag = True if think else None

    try:
        res = CLIENT.chat(messages, model=model, options=options, think=think_flag)
    except Exception as e:  # loguj też błędne strzały (timeout/błąd modelu) — to też dane
        aid = DB.log_attack(
            model=model, messages=messages, response="", session=session or None,
            conversation_id=st["conversation_id"], turn_index=st["turn_index"],
            base_url=CLIENT.base_url, options=options, system_prompt=sysp or None,
            goal=goal or None, technique=technique or None, verdict="error", error=str(e),
        )
        st["last_id"] = aid
        return "", "", f"❌ BŁĄD modelu — zalogowano #{aid} (verdict=error): {e}", st, _stats_md(), _recent_rows()

    aid = DB.log_attack(
        model=model, messages=messages, response=res.content, session=session or None,
        conversation_id=st["conversation_id"], turn_index=st["turn_index"], base_url=CLIENT.base_url,
        options=options, system_prompt=sysp or None, goal=goal or None, technique=technique or None,
        reasoning=res.reasoning, latency_ms=res.latency_ms, eval_count=res.eval_count,
    )
    st["last_id"] = aid
    if multi:  # dopisz do historii dopiero po udanej turze
        st["history"] = st.get("history", []) + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": res.content},
        ]
        st["turn_index"] = st.get("turn_index", 0) + 1

    meta = (f"**#{aid}**  ·  {res.latency_ms} ms"
            + (f"  ·  {res.eval_count} tok" if res.eval_count else "")
            + "  →  oceń niżej: **WIN** / partial / refused")
    return (res.content or "(pusta odpowiedź)"), (res.reasoning or ""), meta, st, _stats_md(), _recent_rows()


def apply_verdict(verdict, st):
    aid = st.get("last_id")
    if not aid:
        return "⚠️ Brak strzału do oceny — najpierw coś wyślij.", _stats_md(), _recent_rows()
    DB.set_verdict(aid, verdict)
    return f"#{aid} → verdict = **{verdict}**", _stats_md(), _recent_rows()


def annotate(tags_str, note, st):
    aid = st.get("last_id")
    if not aid:
        return "⚠️ Brak strzału — najpierw coś wyślij."
    done = []
    if tags_str and tags_str.strip():
        tags = [t.strip() for t in tags_str.replace(",", " ").split() if t.strip()]
        if tags:
            DB.add_tags(aid, tags); done.append(f"tagi {tags}")
    if note and note.strip():
        DB.add_note(aid, note.strip()); done.append("notatka")
    return f"#{aid} += {', '.join(done)}" if done else "⚠️ Nic nie podano do zapisania."


def reset_conversation():
    return fresh_state(), "🔄 Nowa rozmowa — historia multi-turn wyczyszczona."


# ---- budowa UI ------------------------------------------------------------
def build_demo() -> gr.Blocks:
    models = _models()
    default_model = config.DEFAULT_MODEL if config.DEFAULT_MODEL in models else (models[0] if models else config.DEFAULT_MODEL)

    with gr.Blocks(title="Jailbreak Lab", theme=gr.themes.Soft()) as demo:
        state = gr.State(fresh_state())
        gr.Markdown(
            "# 🧪 Jailbreak Lab — GUI\n"
            "Wklejasz prompt (wiele linii OK), narzędzie rozmawia z modelem i **loguje każdy strzał** "
            "do tej samej bazy co REPL. Po odpowiedzi oceniasz: **WIN / partial / refused**."
        )

        with gr.Row():
            # --- lewa kolumna: kontekst ataku (ustawiasz raz, wchodzi do każdego logu) ---
            with gr.Column(scale=1):
                model = gr.Dropdown(choices=models, value=default_model, label="Model", allow_custom_value=True)
                session = gr.Textbox(value=f"gui-{uuid.uuid4().hex[:6]}", label="Sesja (grupowanie w bazie)")
                goal = gr.Textbox(label="Cel (goal) — jakie zachowanie wywołać", lines=2)
                technique = gr.Dropdown(choices=_techniques(), label="Technika", allow_custom_value=True, value=None)
                system_prompt = gr.Textbox(label="System prompt (opcjonalnie — puste = goły model)", lines=2)
                temperature = gr.Slider(0.0, 2.0, value=config.DEFAULT_TEMPERATURE, step=0.05, label="Temperatura")
                with gr.Row():
                    multi = gr.Checkbox(label="Multi-turn (crescendo)", value=False)
                    think = gr.Checkbox(label="Think (reasoning)", value=False)
                reset_btn = gr.Button("🔄 Nowa rozmowa (reset multi-turn)")

            # --- prawa kolumna: atak + odpowiedź + ocena ---
            with gr.Column(scale=2):
                prompt = gr.Textbox(
                    label="Prompt ataku", lines=10,
                    placeholder="Wklej tu prompt. Wiele linii jest OK — idzie jako JEDEN strzał.",
                )
                send_btn = gr.Button("🚀 Wyślij", variant="primary")
                status = gr.Markdown()
                response = gr.Textbox(label="Odpowiedź modelu", lines=14, show_copy_button=True)
                with gr.Accordion("🧠 [thinking] — kanał myślenia (jeśli był)", open=False):
                    reasoning = gr.Textbox(label="", lines=6, show_copy_button=True)
                with gr.Row():
                    win_btn = gr.Button("✅ WIN (success)", variant="primary")
                    partial_btn = gr.Button("🟡 partial", variant="secondary")
                    refused_btn = gr.Button("❌ refused", variant="stop")
                with gr.Row():
                    tags_in = gr.Textbox(label="tagi (przecinki/spacje)", scale=2)
                    note_in = gr.Textbox(label="notatka", scale=3)
                    annotate_btn = gr.Button("💾 zapisz", scale=1)

        with gr.Accordion("📊 Statystyki + ostatnie strzały", open=True):
            stats_md = gr.Markdown(_stats_md())
            recent = gr.Dataframe(
                headers=["#", "model", "verdict", "prompt"],
                datatype=["number", "str", "str", "str"],
                value=_recent_rows(), wrap=True, interactive=False, label="Ostatnie 15 strzałów",
            )
            refresh_btn = gr.Button("Odśwież")

        # --- wiring ---
        send_inputs = [prompt, model, session, goal, technique, system_prompt, temperature, multi, think, state]
        send_btn.click(send, inputs=send_inputs,
                       outputs=[response, reasoning, status, state, stats_md, recent])

        win_btn.click(lambda st: apply_verdict("success", st), inputs=state, outputs=[status, stats_md, recent])
        partial_btn.click(lambda st: apply_verdict("partial", st), inputs=state, outputs=[status, stats_md, recent])
        refused_btn.click(lambda st: apply_verdict("refused", st), inputs=state, outputs=[status, stats_md, recent])

        annotate_btn.click(annotate, inputs=[tags_in, note_in, state], outputs=status)
        reset_btn.click(reset_conversation, outputs=[state, status])
        refresh_btn.click(lambda: (_stats_md(), _recent_rows()), outputs=[stats_md, recent])

    return demo


def main() -> None:
    demo = build_demo()
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True, show_api=False)


if __name__ == "__main__":
    main()
