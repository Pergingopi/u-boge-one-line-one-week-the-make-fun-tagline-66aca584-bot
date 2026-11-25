"""One Line, One Week: The make.fun Tagline.

Writes a single tagline (at most 100 characters) to entry.txt.

Tagline (57 chars, KEPT after revision):
    "AI agents take the bounty. The best entry takes the cash."

Why it is kept -- judged against the brief (land in a single read, true
and specific about make.fun, worth repeating; 1,032 entrants, so the line
must be sharp):
  * True and specific: it carries all three facts from the brief -- AI
    agents enter bounties, the best entry wins, the reward is cash.
  * Lands in one read: two short parallel clauses, "take the bounty" /
    "takes the cash", one breath, easy to repeat.
  * No wasted word: every word names the mechanism or the payoff.

Alternatives considered and rejected:
  1. "AI agents build. The best entry wins the cash." (48 chars)
     Drops "bounty", the core mechanic word; "build" is generic.
  2. "Agents compete. The best build takes the bounty." (49 chars)
     Drops "AI" and the cash payoff; "best build" is vaguer than
     "best entry".
  3. "AI agents chase bounties. The best one cashes in." (50 chars)
     "Cashes in" is slangy, "chase" is weaker than "take", and the
     clean parallel structure is lost.

Hardened gate (revision): at most 100 chars, exactly one line, no
leading/trailing whitespace, and no invisible character at all -- not
just ASCII controls, but every Unicode control/format/surrogate
character (categories Cc, Cf, Cs) and line/paragraph separators
(U+2028, U+2029). A tagline that looks clean but hides a zero-width
character must fail before it ever reaches disk.

Write path (revision): the output directory is resolved and checked
first (empty env falls back to /output, a relative path is made
absolute, an existing non-directory is rejected with a clear error);
stale temp files from an earlier killed run are swept before writing
(only our own prefix, only files older than 10 s, so a concurrent
fresh run is never touched); the entry is written to a temp file in
the same directory, fsynced, atomically renamed over the target, and
read back byte-for-byte. Directory fsync is best-effort (some
filesystems refuse it) while file fsync stays strict, so a sandbox
that cannot fsync a directory still produces a verified entry
instead of failing on bookkeeping.

Standard library only. Deterministic: the same bytes every run.
"""

import os
import stat
import sys
import tempfile
import time
import unicodedata

TAGLINE = "AI agents take the bounty. The best entry takes the cash."

MAX_CHARS = 100

# Temp files this entrypoint creates; the sweep only ever removes these.
_TMP_PREFIX = ".entry-"
_TMP_SUFFIX = ".tmp"
# A temp file younger than this may belong to a concurrent run: leave it.
_STALE_AFTER_SECONDS = 10.0


def _validate(text):
    """Gate: 1-100 chars, single line, no control/invisible characters.

    Rejects ASCII controls, C1 controls, Unicode format characters
    (zero-width space, soft hyphen, BOM, ...), lone surrogates, and
    line/paragraph separators -- anything that would make the line
    look different from what it is, or break the single-line rule
    without a visible newline. Also rejects leading/trailing
    whitespace: a tagline must start and end on a visible word.
    """
    if not isinstance(text, str):
        raise ValueError("entry is not text")
    if not text or not text.strip():
        raise ValueError("entry is empty or only whitespace")
    if text != text.strip():
        raise ValueError("entry has leading or trailing whitespace")
    if len(text) > MAX_CHARS:
        raise ValueError(
            "entry is %d chars, over the 100-char gate" % len(text)
        )
    if "\n" in text or "\r" in text:
        raise ValueError("entry must be a single line")
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Cs", "Zl", "Zp"):
            raise ValueError(
                "entry contains invisible character U+%04X (%s)"
                % (ord(ch), cat)
            )
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValueError(
                "entry contains a control character U+%04X" % ord(ch)
            )
    text.encode("utf-8")  # must be valid UTF-8 text
    return text


def _resolve_out_dir():
    """Resolve MAKEFUN_OUTPUT_DIR to an absolute, existing directory.

    Empty or whitespace-only env falls back to /output. A relative
    path is made absolute so the run log names one stable location.
    An existing path that is not a directory is rejected up front
    instead of failing later inside makedirs with a generic error.
    """
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or ""
    out_dir = out_dir.strip() or "/output"
    out_dir = os.path.abspath(out_dir)
    if os.path.lexists(out_dir) and not os.path.isdir(out_dir):
        raise ValueError(
            "MAKEFUN_OUTPUT_DIR %r exists and is not a directory" % out_dir
        )
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isdir(out_dir):
        raise ValueError(
            "MAKEFUN_OUTPUT_DIR %r is not a directory after creation"
            % out_dir
        )
    return out_dir


def _sweep_stale_tmps(out_dir):
    """Remove temp files left by an earlier killed run, best-effort.

    Only files with our own prefix/suffix in the output directory,
    and only ones older than _STALE_AFTER_SECONDS, so a temp file a
    concurrent fresh run is still writing is never touched. Any
    failure here is ignored: a leftover temp file is clutter, not a
    reason to lose the entry.
    """
    now = time.time()
    try:
        names = os.listdir(out_dir)
    except OSError:
        return 0
    removed = 0
    for name in names:
        if not (
            name.startswith(_TMP_PREFIX) and name.endswith(_TMP_SUFFIX)
        ):
            continue
        path = os.path.join(out_dir, name)
        try:
            if not os.path.isfile(path):
                continue
            if now - os.path.getmtime(path) <= _STALE_AFTER_SECONDS:
                continue
            os.unlink(path)
            removed += 1
        except OSError:
            continue
    return removed


def _fsync_dir(path):
    """Best-effort directory fsync.

    Some filesystems refuse to fsync a directory; that must not fail
    the run -- the file itself is fsynced strictly before the rename,
    and the read-back below verifies what landed on disk.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def main():
    text = _validate(TAGLINE)

    out_dir = _resolve_out_dir()
    stale = _sweep_stale_tmps(out_dir)

    target = os.path.join(out_dir, "entry.txt")

    # Write to a temp file in the same directory, then atomically replace.
    fd, tmp_path = tempfile.mkstemp(
        prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX, dir=out_dir
    )
    try:
        os.chmod(tmp_path, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
        os.chmod(target, 0o644)
        _fsync_dir(out_dir)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Read back and validate what actually landed on disk.
    with open(target, "r", encoding="utf-8", newline="") as f:
        written = f.read()
    if written != text + "\n":
        raise ValueError("read-back mismatch: entry.txt does not hold the tagline")
    if written.count("\n") != 1 or not written.endswith("\n"):
        raise ValueError("read-back mismatch: entry.txt is not exactly one line")
    _validate(written.rstrip("\n"))
    mode = stat.S_IMODE(os.stat(target).st_mode)
    if mode != 0o644:
        raise ValueError("entry.txt mode is %o, expected 0644" % mode)

    sys.stdout.write(
        "wrote %s (%d chars, %d stale tmp(s) swept)\n"
        % (target, len(text), stale)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
