"""
Unit testy archiwum generacji (`hyperagent/archive/store.py`) — mockowany
`audit_db` (BYTEA reprezentowane jako zwykłe `bytes` w pamięci testu, nie
prawdziwy Postgres) + prawdziwy `tarfile`/system plików na `tmp_path`.

Sprawdzamy:
- `pack_workspace`/`unpack_into`: snapshot/restore drzewa kodu jest wierny
  1:1 (pliki, podkatalogi, treść) i ODRZUCA archiwa próbujące wyjść poza
  katalog docelowy (path traversal w nazwach wpisów — agent kontroluje
  ZAWARTOŚĆ plików w /workspace, więc archiwum trzeba traktować jak
  niezaufane wejście przy rozpakowywaniu, mirror `seed/tools.py:_resolve_in_workspace`)
- `select_parent`: strategie `latest`/`best_score` wybierają właściwą gałąź
  drzewa generacji (w tym remis i generacje bez wyniku)
- `checkout`/`snapshot_generation`/`seed_generation`: poprawnie spinają
  warstwę plikową z `audit_db` (rodowód, score, evidence, run_ids 1:1)
"""
from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hyperagent.archive import store


# ----------------------------------------------------------------------
# pack_workspace / unpack_into — wierność snapshotu i odporność na traversal
# ----------------------------------------------------------------------

def _write_tree(root: Path) -> None:
    (root / "main.py").write_text("print('gen')\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "tools.py").write_text("TOOLS = {}\n", encoding="utf-8")
    (root / "sub" / "deep").mkdir()
    (root / "sub" / "deep" / "notes.txt").write_text("zażółć gęślą jaźń\n", encoding="utf-8")


def _read_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class TestPackUnpackRoundTrip:
    def test_round_trip_preserves_files_and_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_tree(src)

        archive_bytes = store.pack_workspace(src)

        dst = tmp_path / "dst"
        store.unpack_into(archive_bytes, dst)

        assert _read_tree(dst) == _read_tree(src)
        assert (dst / "sub" / "deep").is_dir()

    def test_unpack_creates_target_directory(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_tree(src)
        archive_bytes = store.pack_workspace(src)

        dst = tmp_path / "fresh" / "workspace"
        assert not dst.exists()
        store.unpack_into(archive_bytes, dst)

        assert (dst / "main.py").read_text(encoding="utf-8") == "print('gen')\n"


class TestUnpackRejectsPathTraversal:
    def _malicious_archive(self, member_name: str) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            payload = b"pwned"
            info = tarfile.TarInfo(name=member_name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        return buf.getvalue()

    def test_rejects_parent_directory_escape(self, tmp_path):
        dst = tmp_path / "workspace"
        archive_bytes = self._malicious_archive("../evil.py")

        with pytest.raises(ValueError, match="poza katalogiem docelowym"):
            store.unpack_into(archive_bytes, dst)

        assert not (tmp_path / "evil.py").exists()

    def test_rejects_absolute_path_member(self, tmp_path):
        dst = tmp_path / "workspace"
        # tarfile normalizuje wiodący '/' przy dodawaniu, więc budujemy
        # TarInfo z absolutną nazwą bezpośrednio — to dokładnie to, czego
        # broni walidacja (nie polegamy na tym, że tar sam to ogarnie).
        archive_bytes = self._malicious_archive("/etc/evil.py")

        with pytest.raises(ValueError, match="poza katalogiem docelowym"):
            store.unpack_into(archive_bytes, dst)


# ----------------------------------------------------------------------
# select_parent — strategie wyboru rodzica
# ----------------------------------------------------------------------

def _gen(n, *, parent=None, score=None):
    return store.Generation(
        id=100 + n, generation_n=n, parent_n=parent, score=score,
        evidence=[], run_ids=[], notes=None,
    )


class TestSelectParent:
    def test_latest_picks_highest_generation_number(self):
        gens = [_gen(0), _gen(2, parent=1), _gen(1, parent=0)]
        assert store.select_parent(gens, method="latest").generation_n == 2

    def test_best_score_picks_attack_success_over_partial_and_blocked(self):
        gens = [
            _gen(0, score=None),
            _gen(1, parent=0, score="BLOCKED"),
            _gen(2, parent=1, score="ATTACK_SUCCESS"),
            _gen(3, parent=2, score="PARTIAL"),
        ]
        assert store.select_parent(gens, method="best_score").generation_n == 2

    def test_best_score_breaks_ties_with_more_recent_generation(self):
        gens = [_gen(0, score="PARTIAL"), _gen(1, parent=0, score="PARTIAL")]
        assert store.select_parent(gens, method="best_score").generation_n == 1

    def test_best_score_treats_unscored_generation_as_worst(self):
        gens = [_gen(0, score=None), _gen(1, parent=0, score="BLOCKED")]
        assert store.select_parent(gens, method="best_score").generation_n == 1

    def test_empty_archive_raises(self):
        with pytest.raises(ValueError, match="Archiwum jest puste"):
            store.select_parent([], method="latest")

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Nieznana strategia"):
            store.select_parent([_gen(0)], method="random")


# ----------------------------------------------------------------------
# checkout / snapshot_generation / seed_generation — spięcie z audit_db
# ----------------------------------------------------------------------

class TestCheckout:
    def test_restores_code_from_archive_into_workspace(self, tmp_path):
        src = tmp_path / "parent_code"
        src.mkdir()
        _write_tree(src)
        archive_bytes = store.pack_workspace(src)

        with patch.object(store, "audit_db") as mock_db:
            mock_db.get_hyperagent_generation_code.return_value = archive_bytes
            workspace = tmp_path / "child_workspace"
            store.checkout("session-1", _gen(3, parent=2), workspace)

        mock_db.get_hyperagent_generation_code.assert_called_once_with("session-1", 3)
        assert _read_tree(workspace) == _read_tree(src)

    def test_raises_when_archive_missing(self, tmp_path):
        with patch.object(store, "audit_db") as mock_db:
            mock_db.get_hyperagent_generation_code.return_value = None
            with pytest.raises(ValueError, match="Brak snapshotu kodu"):
                store.checkout("session-1", _gen(5), tmp_path / "ws")


class TestSnapshotGeneration:
    def test_packs_workspace_and_saves_metadata(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        _write_tree(ws)

        with patch.object(store, "audit_db") as mock_db:
            mock_db.save_hyperagent_generation.return_value = 42
            generation = store.snapshot_generation(
                "session-1", generation_n=2, parent_n=1, workspace_dir=ws,
                score="PARTIAL", evidence=["x"], run_ids=["run-a"], notes="próba #2",
            )

        assert generation == store.Generation(
            id=42, generation_n=2, parent_n=1, score="PARTIAL",
            evidence=["x"], run_ids=["run-a"], notes="próba #2",
        )
        ((session_id, gen_n, parent_n, archive_bytes), kwargs) = mock_db.save_hyperagent_generation.call_args
        assert (session_id, gen_n, parent_n) == ("session-1", 2, 1)
        assert kwargs == {"score": "PARTIAL", "evidence": ["x"], "run_ids": ["run-a"], "notes": "próba #2"}

        # zapisany blob musi się rozpakować z powrotem do tej samej treści
        restored = tmp_path / "restored"
        store.unpack_into(archive_bytes, restored)
        assert _read_tree(restored) == _read_tree(ws)


class TestSeedGeneration:
    def test_copies_seed_files_and_snapshots_as_generation_zero(self, tmp_path):
        ws = tmp_path / "gen0_workspace"

        with patch.object(store, "audit_db") as mock_db:
            mock_db.save_hyperagent_generation.return_value = 1
            generation = store.seed_generation("session-1", ws)

        assert generation.generation_n == 0
        assert generation.parent_n is None
        assert generation.id == 1

        for name in store.SEED_FILES:
            assert (ws / name).read_text(encoding="utf-8") == (store.SEED_DIR / name).read_text(encoding="utf-8")

        (session_id, gen_n, parent_n, _archive), kwargs = mock_db.save_hyperagent_generation.call_args
        assert (session_id, gen_n, parent_n) == ("session-1", 0, None)
        assert kwargs["notes"] == "seed"
