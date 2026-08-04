"""GUI for building the knowledge base — human in the loop (Tkinter).

Pick a model, choose a category, optionally brainstorm topic ideas and give an instruction,
generate a batch, then review each entry as an EDITABLE card and save / regenerate / remove it
individually. Model calls run in a background thread so the window never freezes; nothing is
written to the DB until you click Save on a card.

Run:  python -m mini_system.kb_studio_gui
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from mini_system.generate_pages import (
    build_llm,
    generate_for_category,
    suggest_topics,
    upsert_page,
)
from mini_system.internet_db import is_sensitive_category, list_categories
from mini_system.kb_studio import MODELS


class KBStudioGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self._llm = None
        self._llm_model = None

        root.title("KB Studio — knowledge base generator")
        root.geometry("900x740")
        self._build_controls()
        self._build_results()
        self.status = tk.Label(root, text="Ready.", anchor="w", fg="#555", padx=10)
        self.status.pack(fill=tk.X, pady=(2, 6))
        self._refresh_existing()
        self.root.after(80, self._drain)

    # ---- model / background plumbing ------------------------------------------------

    def _llm_for(self, model: str):
        if model != self._llm_model:
            self._llm = build_llm(model=model)
            self._llm_model = model
        return self._llm

    def _submit(self, work, done) -> None:
        """Run `work()` in a thread; `done(result, error)` is called on the UI thread."""
        def run():
            try:
                self.q.put((done, work(), None))
            except Exception as exc:  # surfaced to the user, never crashes the UI
                self.q.put((done, None, exc))
        threading.Thread(target=run, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                done, result, error = self.q.get_nowait()
                done(result, error)
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _status(self, text: str) -> None:
        self.status.config(text=text)

    # ---- UI --------------------------------------------------------------------------

    def _build_controls(self) -> None:
        top = tk.Frame(self.root, padx=10, pady=10)
        top.pack(fill=tk.X)

        r1 = tk.Frame(top)
        r1.pack(fill=tk.X)
        tk.Label(r1, text="Model:").pack(side=tk.LEFT)
        self.model_var = tk.StringVar(value=MODELS[0])
        ttk.Combobox(r1, textvariable=self.model_var, values=MODELS, width=50).pack(side=tk.LEFT, padx=6)
        tk.Label(r1, text="Count:").pack(side=tk.LEFT, padx=(10, 0))
        self.count_var = tk.IntVar(value=3)
        tk.Spinbox(r1, from_=1, to=10, width=4, textvariable=self.count_var).pack(side=tk.LEFT, padx=6)

        r2 = tk.Frame(top)
        r2.pack(fill=tk.X, pady=(8, 0))
        tk.Label(r2, text="Category:").pack(side=tk.LEFT)
        self.cat_var = tk.StringVar()
        tk.Entry(r2, textvariable=self.cat_var, width=22).pack(side=tk.LEFT, padx=6)
        tk.Label(r2, text="Instruction:").pack(side=tk.LEFT)
        self.instr_var = tk.StringVar()
        tk.Entry(r2, textvariable=self.instr_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        r3 = tk.Frame(top)
        r3.pack(fill=tk.X, pady=(8, 0))
        self.suggest_btn = tk.Button(r3, text="Suggest topics", command=self._on_suggest)
        self.suggest_btn.pack(side=tk.LEFT)
        self.gen_btn = tk.Button(r3, text="Generate", command=self._on_generate)
        self.gen_btn.pack(side=tk.LEFT, padx=6)

        self.suggest_frame = tk.Frame(top)
        self.suggest_frame.pack(fill=tk.X, pady=(8, 0))
        self.existing_lbl = tk.Label(top, text="", fg="#888", anchor="w", justify=tk.LEFT, wraplength=860)
        self.existing_lbl.pack(fill=tk.X, pady=(8, 0))

    def _build_results(self) -> None:
        wrap = tk.Frame(self.root)
        wrap.pack(fill=tk.BOTH, expand=True, padx=10)
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.results = tk.Frame(self.canvas)
        self.results.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.results, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def _refresh_existing(self) -> None:
        cats = list_categories()
        self.existing_lbl.config(text="Existing: " + (", ".join(f"{c}({n})" for c, n in cats) or "(none)"))

    # ---- actions ---------------------------------------------------------------------

    def _on_suggest(self) -> None:
        category = self.cat_var.get().strip()
        if not category:
            self._status("Enter a category first.")
            return
        for w in self.suggest_frame.winfo_children():
            w.destroy()
        self.suggest_btn.config(state=tk.DISABLED)
        self._status("Brainstorming topic ideas...")
        model = self.model_var.get()
        self._submit(lambda: suggest_topics(self._llm_for(model), category), self._on_suggested)

    def _on_suggested(self, topics, error) -> None:
        self.suggest_btn.config(state=tk.NORMAL)
        if error:
            self._status(f"Error: {error}")
            return
        tk.Label(self.suggest_frame, text="ideas:", fg="#888").pack(side=tk.LEFT)
        for t in topics or []:
            tk.Button(self.suggest_frame, text=t, relief=tk.GROOVE,
                      command=lambda t=t: self.instr_var.set(t)).pack(side=tk.LEFT, padx=3)
        self._status(f"{len(topics or [])} ideas — click one to use it as the focus.")

    def _on_generate(self) -> None:
        category = self.cat_var.get().strip()
        if not category:
            self._status("Enter a category first.")
            return
        try:
            n = max(1, min(10, int(self.count_var.get())))
        except Exception:
            n = 3
        instruction = self.instr_var.get().strip()
        model = self.model_var.get()
        self.gen_btn.config(state=tk.DISABLED)
        self._status(f"Generating {n} for '{category}' with {model}...")
        self._submit(lambda: generate_for_category(self._llm_for(model), category, n, instruction),
                     self._on_generated)

    def _on_generated(self, pages, error) -> None:
        self.gen_btn.config(state=tk.NORMAL)
        if error:
            self._status(f"Error: {error}")
            return
        if not pages:
            self._status("Nothing parsed (format drift — try fewer entries or another model).")
            return
        for p in pages:
            self._add_card(p)
        self._status(f"Generated {len(pages)} — edit if you like, then Save each.")

    # ---- one editable review card ----------------------------------------------------

    def _add_card(self, page: dict) -> None:
        state = {"category": page["category"], "topic": page["topic"],
                 "instruction": self.instr_var.get().strip()}
        sens = is_sensitive_category(state["category"])

        card = tk.Frame(self.results, bd=1, relief=tk.SOLID)
        card.pack(fill=tk.X, pady=6, padx=2)
        inner = tk.Frame(card, padx=10, pady=8)
        inner.pack(fill=tk.X)

        header = tk.Label(inner, anchor="w", font=("Segoe UI", 9, "bold"),
                          fg="#b42318" if sens else "#137a3e")
        header.pack(fill=tk.X)

        def set_header():
            header.config(text=f"{state['category']}/{state['topic']}" + ("   [SENSITIVE]" if sens else ""))
        set_header()

        title_var = tk.StringVar(value=page["title"])
        tk.Entry(inner, textvariable=title_var, font=("Segoe UI", 11, "bold")).pack(fill=tk.X, pady=(4, 4))
        content = tk.Text(inner, height=5, wrap=tk.WORD, font=("Segoe UI", 10))
        content.insert("1.0", page["content"])
        content.pack(fill=tk.X)

        bar = tk.Frame(inner)
        bar.pack(fill=tk.X, pady=(6, 0))
        save_btn = tk.Button(bar, text="Save to DB")
        save_btn.pack(side=tk.LEFT)
        regen_btn = tk.Button(bar, text="Regenerate")
        regen_btn.pack(side=tk.LEFT, padx=6)
        tk.Button(bar, text="Remove", command=card.destroy).pack(side=tk.LEFT)
        note = tk.Label(bar, text="", fg="#555")
        note.pack(side=tk.LEFT, padx=10)

        def do_save():
            pg = {"category": state["category"], "topic": state["topic"],
                  "title": title_var.get().strip(), "content": content.get("1.0", "end").strip()}
            if not pg["title"] or not pg["content"]:
                note.config(text="title/content empty", fg="#b42318")
                return
            save_btn.config(state=tk.DISABLED)
            note.config(text="saving...", fg="#555")

            def done(_res, error):
                if error:
                    note.config(text=f"error: {error}", fg="#b42318")
                    save_btn.config(state=tk.NORMAL)
                    return
                note.config(text="saved ✓", fg="#137a3e")
                regen_btn.config(state=tk.DISABLED)
                self._refresh_existing()
            self._submit(lambda: upsert_page(pg), done)

        def do_regen():
            regen_btn.config(state=tk.DISABLED)
            note.config(text="regenerating...", fg="#555")
            model = self.model_var.get()

            def done(res, error):
                regen_btn.config(state=tk.NORMAL)
                if error:
                    note.config(text=f"error: {error}", fg="#b42318")
                    return
                if not res:
                    note.config(text="nothing generated", fg="#b42318")
                    return
                fresh = res[0]
                state["topic"] = fresh["topic"]
                set_header()
                title_var.set(fresh["title"])
                content.delete("1.0", "end")
                content.insert("1.0", fresh["content"])
                note.config(text="", fg="#555")
            self._submit(
                lambda: generate_for_category(self._llm_for(model), state["category"], 1, state["instruction"]),
                done,
            )

        save_btn.config(command=do_save)
        regen_btn.config(command=do_regen)


def main() -> None:
    root = tk.Tk()
    KBStudioGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
