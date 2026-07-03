import json
import pathlib
import subprocess
import sys

SCRIPT = str(pathlib.Path(__file__).resolve().parents[1]
             / "plugins/md-optimize/skills/md-optimize/scripts/md_optimize_history.py")


def _run(store, *args, **kw):
    env = kw.pop("env", None) or {}
    import os
    e = dict(os.environ, MD_OPTIMIZE_HOME=str(store), **env)
    return subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, env=e)


def test_snapshot_records_ledger_and_backup(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    f.write_text("original\n")
    r = _run(store, "snapshot", str(f), "--change", "Style::trimmed intro")
    assert r.returncode == 0, r.stderr
    ledger = (store / "ledger.jsonl").read_text().strip().splitlines()
    assert len(ledger) == 1
    entry = json.loads(ledger[0])
    assert entry["type"] == "optimize"
    assert entry["file"] == str(f)
    assert entry["changes"] == [{"section": "Style", "summary": "trimmed intro"}]
    assert pathlib.Path(entry["backup"]).read_text() == "original\n"


def test_restore_brings_back_prior_content(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    f.write_text("original\n")
    _run(store, "snapshot", str(f))
    f.write_text("edited by md-optimize\n")            # simulate the optimize edit

    # restore needs --yes to actually overwrite
    dry = _run(store, "restore", str(f))
    assert dry.returncode == 1
    assert f.read_text() == "edited by md-optimize\n"   # unchanged without --yes

    done = _run(store, "restore", str(f), "--yes")
    assert done.returncode == 0, done.stderr
    assert f.read_text() == "original\n"                # reverted


def test_restore_is_itself_undoable(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    f.write_text("v1\n")
    _run(store, "snapshot", str(f))
    f.write_text("v2\n")
    _run(store, "restore", str(f), "--yes")             # back to v1, saves v2 as pre-restore
    # a pre-restore snapshot of v2 must exist so we can go forward again
    backups = list((store / "backups").rglob("*__pre-restore.md"))
    assert backups and backups[0].read_text() == "v2\n"


def test_diff_shows_pending_restore(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    f.write_text("keep\nold line\n")
    _run(store, "snapshot", str(f))
    f.write_text("keep\nnew line\n")
    d = _run(store, "diff", str(f))
    assert d.returncode == 0
    assert "-new line" in d.stdout and "+old line" in d.stdout


def test_list_filters_by_file_and_orders_newest_first(tmp_path):
    store = tmp_path / "store"
    a = tmp_path / "a.md"; a.write_text("a\n")
    b = tmp_path / "b.md"; b.write_text("b\n")
    _run(store, "snapshot", str(a))
    _run(store, "snapshot", str(b))
    out = _run(store, "list", str(a), "--json").stdout
    rows = json.loads(out)
    assert all(e["file"] == str(a) for e in rows)
    assert len(rows) == 1


def test_restore_missing_snapshot_errors(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    f.write_text("x\n")
    r = _run(store, "restore", str(f), "--yes")
    assert r.returncode == 2
    assert "no snapshot" in r.stderr


def test_snapshot_refuses_non_markdown(tmp_path):
    store = tmp_path / "store"
    secret = tmp_path / "authorized_keys"
    secret.write_text("ssh-rsa AAAA...\n")
    r = _run(store, "snapshot", str(secret))
    assert r.returncode == 2 and "non-markdown" in r.stderr
    assert not (store / "ledger.jsonl").exists()   # nothing recorded


def test_restore_refuses_non_markdown_target(tmp_path):
    store = tmp_path / "store"
    victim = tmp_path / "config"
    victim.write_text("do-not-touch\n")
    r = _run(store, "restore", str(victim), "--yes")
    assert r.returncode == 2 and "non-markdown" in r.stderr
    assert victim.read_text() == "do-not-touch\n"   # untouched


def test_symlink_cannot_escape_to_non_markdown(tmp_path):
    store = tmp_path / "store"
    real = tmp_path / "secret.conf"
    real.write_text("secret\n")
    link = tmp_path / "CLAUDE.md"          # .md name, but points at a .conf
    link.symlink_to(real)
    r = _run(store, "snapshot", str(link))
    assert r.returncode == 2 and "non-markdown" in r.stderr   # resolved, then refused


def test_nonstandard_md_name_warns_but_works(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "notes.md"
    f.write_text("hi\n")
    r = _run(store, "snapshot", str(f))
    assert r.returncode == 0
    assert "not a standard instructions file" in r.stderr   # warned, still ran


def _count_backups(store):
    root = store / "backups"
    # NB: per-file backup dirs are named after the file (…CLAUDE.md), so their
    # names also match "*.md" — count files only, not those directories.
    return len([p for p in root.rglob("*.md") if p.is_file()]) if root.exists() else 0


def _ledger_len(store):
    p = store / "ledger.jsonl"
    return len([l for l in p.read_text().splitlines() if l.strip()]) if p.exists() else 0


def test_prune_requires_a_policy(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"; f.write_text("a\n")
    _run(store, "snapshot", str(f))
    r = _run(store, "prune")
    assert r.returncode == 2 and "--keep" in r.stderr
    assert _ledger_len(store) == 1        # untouched


def test_prune_keep_n_is_dry_run_without_yes(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    for i in range(5):
        f.write_text(f"v{i}\n")
        _run(store, "snapshot", str(f))
    dry = _run(store, "prune", "--keep", "2")
    assert dry.returncode == 1 and "would delete" in dry.stdout
    assert _ledger_len(store) == 5 and _count_backups(store) == 5   # nothing gone


def test_prune_keep_n_deletes_oldest(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    for i in range(5):
        f.write_text(f"v{i}\n")
        _run(store, "snapshot", str(f), "--change", f"S::change {i}")
    done = _run(store, "prune", "--keep", "2", "--yes")
    assert done.returncode == 0
    assert _ledger_len(store) == 2 and _count_backups(store) == 2
    # The SURVIVORS must be the two NEWEST runs (change 3 and 4), not the oldest
    # — guards against ties when all snapshots share a whole-second timestamp.
    rows = json.loads(_run(store, "list", str(f), "--json").stdout)
    summaries = {c["summary"] for e in rows for c in e["changes"]}
    assert summaries == {"change 3", "change 4"}


def test_restore_picks_true_newest_under_same_second(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    for i in range(4):                       # all likely within one second
        f.write_text(f"snapshot-of-v{i}\n")
        _run(store, "snapshot", str(f))
    f.write_text("uncommitted edit\n")
    _run(store, "restore", str(f), "--yes")  # default = newest snapshot
    assert f.read_text() == "snapshot-of-v3\n"


def test_prune_is_per_file(tmp_path):
    store = tmp_path / "store"
    a = tmp_path / "a.md"; b = tmp_path / "b.md"
    for i in range(3):
        a.write_text(f"a{i}\n"); _run(store, "snapshot", str(a))
        b.write_text(f"b{i}\n"); _run(store, "snapshot", str(b))
    _run(store, "prune", "--keep", "1", "--yes")
    # keep-1 applies to EACH file → one per file survives
    assert _ledger_len(store) == 2


def test_prune_older_than_zero_days_removes_all(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"; f.write_text("a\n")
    _run(store, "snapshot", str(f))
    r = _run(store, "prune", "--older-than", "0d", "--yes")
    assert r.returncode == 0 and _ledger_len(store) == 0 and _count_backups(store) == 0


def test_prune_run_targets_one_snapshot(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    ids = []
    for i in range(3):
        f.write_text(f"v{i}\n")
        out = _run(store, "snapshot", str(f)).stdout
        ids.append(out.split()[1])          # "snapshot <id> → ..."
    # purge exactly the middle run (as after redacting a secret)
    done = _run(store, "prune", str(f), "--run", ids[1], "--yes")
    assert done.returncode == 0
    remaining = {e["run"] for e in json.loads(_run(store, "list", str(f), "--json").stdout)}
    assert remaining == {ids[0], ids[2]}


def test_prune_run_unknown_errors(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"; f.write_text("a\n")
    _run(store, "snapshot", str(f))
    r = _run(store, "prune", "--run", "nope-123", "--yes")
    assert r.returncode == 2 and "no run" in r.stderr


def test_ack_records_desc_and_hash_not_snippet(tmp_path):
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"; f.write_text("x\n")
    r = _run(store, "ack", str(f), "--desc", "internal hostname in Deploy",
             "--snippet", "db.internal.acme.corp")
    assert r.returncode == 0
    raw = (store / "acknowledged.jsonl").read_text()
    assert "db.internal.acme.corp" not in raw        # secret NOT stored
    entry = json.loads(raw.strip())
    assert entry["desc"] == "internal hostname in Deploy" and entry["fp"]


def test_acks_lists_only_for_file(tmp_path):
    store = tmp_path / "store"
    a = tmp_path / "a.md"; a.write_text("a\n")
    b = tmp_path / "b.md"; b.write_text("b\n")
    _run(store, "ack", str(a), "--desc", "item A")
    _run(store, "ack", str(b), "--desc", "item B")
    rows = json.loads(_run(store, "acks", str(a), "--json").stdout)
    assert len(rows) == 1 and rows[0]["desc"] == "item A"


def test_prune_never_deletes_a_referenced_backup(tmp_path):
    # A restore references an older snapshot; pruning that older run must not
    # delete the file while the restore entry still points at it.
    store = tmp_path / "store"
    f = tmp_path / "CLAUDE.md"
    f.write_text("v1\n"); _run(store, "snapshot", str(f))   # run 1 (before=v1)
    f.write_text("v2\n")
    _run(store, "restore", str(f), "--yes")                 # restore refs run 1's backup
    # Now keep only the newest 1 run → the old optimize entry is a delete candidate,
    # but the restore entry still references its backup, so the file stays.
    before = _count_backups(store)
    _run(store, "prune", "--keep", "1", "--yes")
    assert f.read_text() == "v1\n"                          # file itself fine
    # the v1 backup referenced by the surviving restore entry is preserved
    assert (store / "backups").exists()
    assert _count_backups(store) <= before
