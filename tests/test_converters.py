"""
Unit testy rejestru komponowalnych konwerterów (attack_core/strategies/converters.py).

Konwertery są czyste i deterministyczne — testujemy je bez DB/LLM. Sprawdzamy:
- parser specu pipeline'u (nazwy, parametry, tolerancja),
- determinizm i odwracalność `encode`,
- że nieznany konwerter trafia do `problems`, a tekst leci dalej nietknięty,
- zachowanie kolejności kroków.
"""
import base64
import codecs

from attack_core.strategies.converters import (
    apply_pipeline,
    list_converters,
    parse_pipeline,
    render_toolbox,
)


# ------------------------------------------------------------------
# Parser specu
# ------------------------------------------------------------------

class TestParsePipeline:
    def test_empty_spec_yields_no_steps(self):
        steps, problems = parse_pipeline("")
        assert steps == [] and problems == []

    def test_single_step_no_args(self):
        steps, problems = parse_pipeline("refusal_suppression")
        assert problems == []
        assert len(steps) == 1
        assert steps[0].name == "refusal_suppression"
        assert steps[0].params == {}

    def test_multiple_steps_with_args(self):
        steps, _ = parse_pipeline('authority_framing(role="IT director") | encode(scheme=base64)')
        assert [s.name for s in steps] == ["authority_framing", "encode"]
        assert steps[0].params == {"role": "IT director"}
        assert steps[1].params == {"scheme": "base64"}

    def test_int_param_is_parsed_as_int(self):
        steps, _ = parse_pipeline("payload_split(parts=3)")
        assert steps[0].params == {"parts": 3}

    def test_single_quoted_value(self):
        steps, _ = parse_pipeline("roleplay_wrap(persona='DevOps bot')")
        assert steps[0].params == {"persona": "DevOps bot"}

    def test_blank_segments_are_skipped(self):
        steps, problems = parse_pipeline("identity ||  | identity")
        assert [s.name for s in steps] == ["identity", "identity"]
        assert problems == []


# ------------------------------------------------------------------
# apply_pipeline
# ------------------------------------------------------------------

class TestApplyPipeline:
    def test_identity_returns_seed_unchanged(self):
        out, applied, problems = apply_pipeline("identity", "hello")
        assert out == "hello"
        assert applied == ["identity"]
        assert problems == []

    def test_unknown_converter_recorded_and_text_passes_through(self):
        out, applied, problems = apply_pipeline("does_not_exist", "hello")
        assert out == "hello"
        assert applied == []
        assert any("nieznany konwerter" in p for p in problems)

    def test_order_is_preserved(self):
        # authority_framing dokłada na początek, urgency też — drugi wrap obejmuje pierwszy
        out, applied, _ = apply_pipeline("authority_framing(role=boss) | urgency(level=high)", "DO X")
        assert applied == ["authority_framing", "urgency"]
        # urgency był ostatni -> jego baner jest na samej górze
        assert out.startswith("PILNE")
        assert "boss" in out
        assert "DO X" in out

    def test_empty_pipeline_returns_seed(self):
        out, applied, problems = apply_pipeline("", "seed text")
        assert out == "seed text"
        assert applied == []
        assert problems == []

    def test_bad_param_does_not_break_pipeline(self):
        # encode z nieznanym scheme -> krok pominięty, tekst leci dalej
        out, applied, problems = apply_pipeline("encode(scheme=nope)", "seed")
        assert out == "seed"
        assert applied == []
        assert any("encode" in p for p in problems)


# ------------------------------------------------------------------
# encode — determinizm i odwracalność
# ------------------------------------------------------------------

class TestEncode:
    def test_base64_roundtrip(self):
        out, applied, _ = apply_pipeline("encode(scheme=base64)", "rm -rf /app/secrets")
        assert applied == ["encode"]
        encoded = out.strip().splitlines()[-1]
        assert base64.b64decode(encoded).decode("utf-8") == "rm -rf /app/secrets"

    def test_rot13_roundtrip(self):
        out, _, _ = apply_pipeline("encode(scheme=rot13)", "secret")
        encoded = out.strip().splitlines()[-1]
        assert codecs.decode(encoded, "rot_13") == "secret"

    def test_hex_roundtrip(self):
        out, _, _ = apply_pipeline("encode(scheme=hex)", "abc")
        encoded = out.strip().splitlines()[-1]
        assert bytes.fromhex(encoded).decode("utf-8") == "abc"

    def test_encode_is_deterministic(self):
        a, _, _ = apply_pipeline("encode(scheme=base64)", "x")
        b, _, _ = apply_pipeline("encode(scheme=base64)", "x")
        assert a == b


# ------------------------------------------------------------------
# Listing toolboxu
# ------------------------------------------------------------------

class TestToolbox:
    def test_list_converters_includes_core(self):
        names = {c["name"] for c in list_converters()}
        assert {"identity", "encode", "authority_framing", "refusal_suppression"} <= names

    def test_render_toolbox_is_nonempty_text(self):
        text = render_toolbox()
        assert "encode" in text and "authority_framing" in text

    def test_translate_marked_needs_llm(self):
        translate = next(c for c in list_converters() if c["name"] == "translate")
        assert translate["needs_llm"] is True

    def test_translate_without_llm_is_noop(self):
        out, applied, problems = apply_pipeline("translate(lang=angielski)", "zrób to")
        assert out == "zrób to"
        assert applied == ["translate"]
        assert problems == []
