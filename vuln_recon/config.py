"""
Konfiguracja adaptera Garak — jedno miejsce na wybór modeli, generatora i probe'ów.

Domyślnie spada na ten sam stack co reszta systemu (`config.settings.ollama_*`), więc bez
konfiguracji „po prostu działa" przeciw lokalnej Ollamie. Zmienne środowiskowe (prefiks
GARAK_, też z .env):

  GARAK_TARGET_MODEL    model ATAKOWANY        (domyślnie = ollama_model, np. gpt-oss:20b)
  GARAK_TARGET_TYPE     generator garak        (domyślnie 'ollama'; też ollama.OllamaGeneratorChat,
                                                openai.OpenAICompatible, rest, nim...)
  GARAK_ATTACKER_MODEL  model red-team/atkgen  (domyślnie None — większość probe'ów statyczna)
  GARAK_BASE_URL        adres Ollamy           (domyślnie = ollama_base_url; → OLLAMA_HOST)
  GARAK_PROBES          spec probe'ów garaka   (domyślnie 'dan.DanInTheWild'; CSV/rodzina, np.
                                                'dan,promptinject' albo 'latentinjection.LatentJailbreak')
  GARAK_REPORT_DIR      katalog raportów       (domyślnie vuln_recon/logs)
  GARAK_EXTRA_ARGS      surowe dodatkowe flagi przepuszczane do garaka (np. '--generations 1')

Flagi garaka zweryfikowane na 0.15.1: target_type/target_name (model_type/model_name
deprecated od 0.13.1).
"""

from __future__ import annotations

import sys

from pydantic_settings import BaseSettings, SettingsConfigDict

from config import settings as _root


class GarakSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GARAK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    target_model: str = _root.ollama_model
    target_type: str = "ollama"
    attacker_model: str | None = None
    # Generator garaka dla modelu ATAKUJĄCEGO (red-team w probe `atkgen`). Musi być w formie
    # moduł.Klasa (garak robi split po kropce). Domyślnie chatowy generator Ollamy, bo nasze
    # modele atakujące (qwen-uncensored) chodzą na Ollamie. Patrz garak_runner._attacker_probe_options.
    attacker_type: str = "ollama.OllamaGeneratorChat"
    base_url: str = _root.ollama_base_url
    probes: str = "dan.DanInTheWild"
    report_dir: str = "vuln_recon/logs"
    python_exe: str = sys.executable
    # Timeout (s) jednego wywołania generatora Ollamy. DOMYŚLNY garaka to 30s — za mało dla
    # zimno-ładowanych modeli rozumujących przy OLLAMA_KEEP_ALIVE=0 (model przeładowuje się co
    # turę). Za krótki timeout → TimeoutException → garak ponawia → burza retry pod presją RAM →
    # Ollama się zakleszcza (zaobserwowany zawis atkgen). Stosujemy do celu i do red-teamu.
    request_timeout: int = 600
    # Objętość atkgen (model-vs-model). None = domyślne garaka (5×5 = 25 konwersacji — przy swapie
    # modeli to godziny). Ustaw mniejsze dla skończonego, turowego przebiegu na słabym RAM.
    atkgen_convs: int | None = None   # convs_per_generation
    atkgen_calls: int | None = None   # max_calls_per_conv
    # Surowe, dodatkowe flagi do garaka (np. ograniczenie liczby generacji) — rozbijane po spacjach.
    extra_args: str = ""

    def probe_list(self) -> list[str]:
        """Spec probe'ów jako lista (do zapisu w recon.scans.probes)."""
        return [p.strip() for p in self.probes.split(",") if p.strip()]
