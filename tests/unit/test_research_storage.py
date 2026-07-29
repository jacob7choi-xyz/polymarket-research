"""Tests for the frozen-dataset capability boundary in research storage.

The research pipeline is otherwise untested exploratory code. These tests exist because
write-prevention on frozen evidence is a security invariant, not exploratory behaviour:
the previous single accessor ran ALTER TABLE merely by connecting, and the metadata
writer erased columns owned by later pipeline stages.

Filesystem permissions are an operational control layered on top of this and are
deliberately not asserted here -- they vary with CI user privileges. The software
boundary is the read-only connection plus the writer guard.
"""

from pathlib import Path
import sqlite3

import pytest

from research.pipeline import storage


@pytest.fixture
def scratch_db(tmp_path: Path) -> Path:
    """A small unprotected database standing in for a live dataset."""
    path = tmp_path / "scratch.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE markets (market_id TEXT PRIMARY KEY, question TEXT)")
    conn.execute("INSERT INTO markets VALUES ('m1', 'Will this test pass?')")
    conn.commit()
    conn.close()
    return path


class TestReadOnlyCapability:
    """A read connection must be able to read, and nothing else."""

    def test_select_succeeds(self, scratch_db: Path) -> None:
        """Reading is the whole point; it must still work."""
        conn = storage.open_readonly(scratch_db)
        try:
            assert conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0] == 1
        finally:
            conn.close()

    def test_update_fails(self, scratch_db: Path) -> None:
        """DML must be rejected."""
        conn = storage.open_readonly(scratch_db)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("UPDATE markets SET question = 'mutated'")
        finally:
            conn.close()

    def test_alter_table_fails(self, scratch_db: Path) -> None:
        """DDL must be rejected -- this is the mutation the old read path performed."""
        conn = storage.open_readonly(scratch_db)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("ALTER TABLE markets ADD COLUMN injected REAL")
        finally:
            conn.close()

    def test_delete_fails(self, scratch_db: Path) -> None:
        """Deletion must be rejected."""
        conn = storage.open_readonly(scratch_db)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("DELETE FROM markets")
        finally:
            conn.close()

    def test_missing_database_is_not_created(self, tmp_path: Path) -> None:
        """A missing evidence store must not become an empty new one.

        sqlite3.connect() creates a database when the file is absent. A forensic read
        path silently manufacturing an empty dataset is the fail-open behaviour this
        boundary exists to prevent.
        """
        absent = tmp_path / "does_not_exist.db"
        with pytest.raises(FileNotFoundError):
            storage.open_readonly(absent)
        assert not absent.exists()

    def test_read_leaves_no_sidecar_files(self, scratch_db: Path) -> None:
        """Reading frozen evidence must not add -journal/-wal/-shm files beside it."""
        before = {p.name for p in scratch_db.parent.iterdir()}
        conn = storage.open_readonly(scratch_db)
        try:
            conn.execute("SELECT COUNT(*) FROM markets").fetchone()
        finally:
            conn.close()
        assert {p.name for p in scratch_db.parent.iterdir()} == before


class TestWriterGuard:
    """Writable entry points must fail closed on frozen datasets."""

    def test_get_connection_refuses_protected_dataset(self) -> None:
        """The v1 database is frozen; the writable path must refuse it."""
        with pytest.raises(storage.FrozenDatasetError, match="frozen dataset"):
            storage.get_connection(storage.DB_PATH)

    def test_get_connection_refuses_archive_root(self, tmp_path: Path) -> None:
        """Anything under the archive root is frozen evidence by definition."""
        archive_child = next(iter(storage.PROTECTED_ROOTS)) / "v1" / "anything.db"
        with pytest.raises(storage.FrozenDatasetError):
            storage.get_connection(archive_child)

    def test_guard_resolves_paths_rather_than_matching_strings(self) -> None:
        """An alternate spelling of a protected path must not slip through.

        String comparison would let ``research/data/../data/markets.db`` past the guard.
        """
        indirect = Path(storage.DB_PATH).parent / ".." / "data" / "markets.db"
        with pytest.raises(storage.FrozenDatasetError):
            storage.assert_writable(indirect)

    def test_guard_follows_symlinks(self, tmp_path: Path) -> None:
        """A symlink pointing at frozen evidence must be refused."""
        link = tmp_path / "innocent_name.db"
        try:
            link.symlink_to(Path(storage.DB_PATH))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")
        with pytest.raises(storage.FrozenDatasetError):
            storage.assert_writable(link)

    def test_unprotected_path_is_allowed(self, tmp_path: Path) -> None:
        """The guard must not block legitimate new datasets."""
        storage.assert_writable(tmp_path / "future_v2.db")

    def test_policy_lock_no_override_parameter(self) -> None:
        """POLICY LOCK: the guard must expose no override parameter.

        This asserts shape rather than behaviour deliberately. Adding a parameter such
        as force= or allow_frozen= would weaken a security invariant without failing any
        behavioural test, so changing this signature should require conscious review
        rather than passing silently.
        """
        import inspect

        params = inspect.signature(storage.assert_writable).parameters
        assert set(params) == {"path"}

    def test_canonical_evidence_copy_is_protected(self) -> None:
        """The off-repo canonical copy must be protected, not just the working copy.

        Regression: protection originally attached only to the in-repo path, so
        get_connection() would happily open the canonical evidence archive writable --
        the artifact with the least redundancy got the least protection.
        """
        manifest = Path("research/archive/v1/manifest.json")
        if not manifest.exists():
            pytest.skip("v1 manifest not present")
        import json

        canonical = Path(json.loads(manifest.read_text())["canonical_copy_path"]).expanduser()
        with pytest.raises(storage.FrozenDatasetError):
            storage.assert_writable(canonical)
        with pytest.raises(storage.FrozenDatasetError):
            storage.assert_writable(canonical.parent / "schema.sql")

    def test_protected_set_derives_from_manifest(self) -> None:
        """Protection is driven by the evidence record, not a hardcoded layout guess."""
        manifest = Path("research/archive/v1/manifest.json")
        if not manifest.exists():
            pytest.skip("v1 manifest not present")
        import json

        canonical = Path(json.loads(manifest.read_text())["canonical_copy_path"]).expanduser()
        assert canonical.resolve() in storage.PROTECTED_DATASETS


class TestManifestDiscoveryFailsClosed:
    """An uninterpretable freeze manifest must refuse, not silently protect less."""

    def test_malformed_manifest_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unparseable JSON means unknown evidence identity, so refuse."""
        archive = tmp_path / "archive"
        (archive / "v9").mkdir(parents=True)
        (archive / "v9" / "manifest.json").write_text("{ not json")
        monkeypatch.setattr(storage, "_ARCHIVE_ROOT", archive)
        with pytest.raises(storage.EvidenceManifestError, match="could not be read"):
            storage._canonical_copies()

    def test_manifest_without_canonical_path_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A manifest that names no canonical asset cannot be acted on."""
        archive = tmp_path / "archive"
        (archive / "v9").mkdir(parents=True)
        (archive / "v9" / "manifest.json").write_text('{"dataset": "v9"}')
        monkeypatch.setattr(storage, "_ARCHIVE_ROOT", archive)
        with pytest.raises(storage.EvidenceManifestError, match="canonical_copy_path"):
            storage._canonical_copies()

    def test_absent_archive_is_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No archive means nothing to discover, which is different from malformed."""
        monkeypatch.setattr(storage, "_ARCHIVE_ROOT", tmp_path / "nonexistent")
        assert storage._canonical_copies() == (set(), set())

    @pytest.mark.parametrize(
        "body",
        [
            "[]",
            "42",
            '"a string"',
            '{"canonical_copy_path": 123}',
            '{"canonical_copy_path": "   "}',
            '{"canonical_copy_path": "relative/markets.db"}',
            '{"canonical_copy_path": "/markets.db"}',
        ],
    )
    def test_uninterpretable_manifests_raise_the_typed_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
    ) -> None:
        """Parsing successfully is not the same as being interpretable.

        Each of these previously escaped the typed contract, as AttributeError,
        TypeError, or by silently succeeding. The relative case resolved against the
        process working directory, so one manifest protected different assets depending
        on where it ran. The filesystem-root case put '/' into PROTECTED_ROOTS, which
        would have made every path on the machine unwritable through this module.
        """
        archive = tmp_path / "archive"
        (archive / "v9").mkdir(parents=True)
        (archive / "v9" / "manifest.json").write_text(body)
        monkeypatch.setattr(storage, "_ARCHIVE_ROOT", archive)
        with pytest.raises(storage.EvidenceManifestError):
            storage._canonical_copies()

    def test_wellformed_manifest_separates_dataset_from_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid manifest protects the file and its directory as distinct sets."""
        archive = tmp_path / "archive"
        (archive / "v9").mkdir(parents=True)
        canonical = tmp_path / "external" / "v9" / "markets.db"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"")
        (archive / "v9" / "manifest.json").write_text(f'{{"canonical_copy_path": "{canonical}"}}')
        monkeypatch.setattr(storage, "_ARCHIVE_ROOT", archive)

        datasets, roots = storage._canonical_copies()

        assert datasets == {canonical.resolve()}
        assert roots == {canonical.parent.resolve()}
        assert canonical.resolve() not in roots


class TestReadOnlyUriSafety:
    """Filenames containing URI syntax must not be misparsed."""

    @pytest.mark.parametrize("name", ["plain.db", "we%ird.db", "quer?y.db", "frag#ment.db"])
    def test_adversarial_filenames_open_correctly(self, tmp_path: Path, name: str) -> None:
        """'?', '#' and '%' are URI syntax; unescaped they would truncate the path."""
        path = tmp_path / name
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()

        ro = storage.open_readonly(path)
        try:
            assert ro.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        finally:
            ro.close()
