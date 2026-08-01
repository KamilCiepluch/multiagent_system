"""Tkinter chat GUI — a thin WRAPPER around ConversationAgent, not an agent itself.

It builds the agent the same way the pipeline does (build_system_llm + MCP tool dict) and
drives its `chat()` / `reset()` methods. The model call runs in a background thread so the
window never freezes; there is no token streaming — the full reply is shown when ready.

Run:  python -m interactive.chat_gui
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

from agents.conversation_agent import ConversationAgent
from agents.stateful_agent import DEFAULT_CONVERSATION_ID
from llm_factory import build_system_llm


def build_chat_agent() -> ConversationAgent:
    """Construct the chat agent like a pipeline node. TOOL_NAMES is empty, so an empty MCP
    tool dict is enough — no MCP server or world needed for plain chat."""
    return ConversationAgent(build_system_llm(), {})


class ChatGUI:
    def __init__(self, root: tk.Tk, agent: ConversationAgent | None = None):
        self.root = root
        self.agent = agent or build_chat_agent()
        self.conversation_id = DEFAULT_CONVERSATION_ID
        self.events: queue.Queue = queue.Queue()

        root.title(f"{self.agent.NAME} — chat")
        root.geometry("640x560")

        self.view = scrolledtext.ScrolledText(root, wrap=tk.WORD, state=tk.DISABLED, font=("Segoe UI", 10))
        self.view.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))
        self.view.tag_config("you", foreground="#1a6fdb", font=("Segoe UI", 10, "bold"))
        self.view.tag_config("bot", foreground="#137a3e", font=("Segoe UI", 10, "bold"))
        self.view.tag_config("sys", foreground="#888888", font=("Segoe UI", 9, "italic"))

        bottom = tk.Frame(root)
        bottom.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.entry = tk.Text(bottom, height=3, wrap=tk.WORD, font=("Segoe UI", 10))
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.entry.bind("<Return>", self._on_return)
        self.entry.focus_set()

        controls = tk.Frame(bottom)
        controls.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        self.send_btn = tk.Button(controls, text="Send", width=8, command=self._send)
        self.send_btn.pack(fill=tk.X)
        tk.Button(controls, text="New chat", width=8, command=self._reset).pack(fill=tk.X, pady=(4, 0))

        self._append("sys", "Enter wysyła, Shift+Enter nowa linia\n")
        self.root.after(50, self._drain)

    def _on_return(self, event):
        if event.state & 0x0001:  # Shift held → newline
            return None
        self._send()
        return "break"

    def _send(self):
        text = self.entry.get("1.0", tk.END).strip()
        if not text:
            return
        self.entry.delete("1.0", tk.END)
        self._append("you", "You: ", newline=False)
        self._append(None, text)
        self._set_busy(True)
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text: str):
        try:
            reply = self.agent.chat(text, conversation_id=self.conversation_id)
        except Exception as exc:  # surface model/DB errors in the window instead of dying
            reply = f"[error: {exc}]"
        self.events.put(reply)

    def _drain(self):
        try:
            while True:
                reply = self.events.get_nowait()
                self._append("bot", "Bot: ", newline=False)
                self._append(None, reply)
                self._set_busy(False)
        except queue.Empty:
            pass
        self.root.after(50, self._drain)

    def _reset(self):
        self.agent.reset(conversation_id=self.conversation_id)
        self._append("sys", "[new conversation]\n")

    def _set_busy(self, busy: bool):
        self.send_btn.config(state=tk.DISABLED if busy else tk.NORMAL)

    def _append(self, tag: str | None, text: str, newline: bool = True):
        self.view.config(state=tk.NORMAL)
        self.view.insert(tk.END, text + ("\n" if newline else ""), (tag,) if tag else ())
        self.view.see(tk.END)
        self.view.config(state=tk.DISABLED)


def main():
    root = tk.Tk()
    ChatGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
