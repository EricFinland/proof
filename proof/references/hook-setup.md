# Hook Setup and Recursion Guard

Proof installs a `Stop` hook. The installed command uses quoted absolute paths:

```
"<python-interpreter>" "<absolute path to proof_trigger.py>"
```

For example, on a typical install:
```
"C:\Python314\python.exe" "C:\Users\you\.claude\skills\proof\scripts\proof_trigger.py"
```

The hook reads `{session_id, transcript_path, stop_hook_active}` from stdin.

## No-op conditions

The hook exits without printing anything (no block) when:

- `stop_hook_active` is `true` in the payload (prevents the hook from blocking
  its own spawned sub-sessions).
- The last assistant message contains no completion claim (classifier returns
  `is_claim = False`).
- The blocking policy (see below) says this claim should not be re-blocked.

## Blocking policy

The policy is tracked in `~/.proof/verified.json` (or `$PROOF_HOME/verified.json`)
keyed by `(session_id, sha256_prefix(claim_text))`.

| State | Action |
|-------|--------|
| Claim never seen in this session | Block. Spawn verifier directive. |
| Last outcome was `pass` | No-op. Claim is proven; never re-block. |
| Last outcome was `inconclusive` | No-op. Nothing more to check automatically. |
| Last outcome was `fail`, attempts < `max_fix_cycles` | Block again with receipts. |
| Attempts >= `max_fix_cycles` (regardless of outcome) | No-op. Give up to avoid infinite nagging. |

`max_fix_cycles` defaults to `3` and can be overridden in `.proof.toml`:

```toml
[verify]
max_fix_cycles = 5
```

## Re-block with receipts

When re-blocking after a prior FAIL (`attempts >= 2` and `last_outcome == "fail"`),
the hook prepends the first 1500 characters of the current `proof-report.md` to
the directive as "PREVIOUS RECEIPTS" and adds a note:

```
This is attempt N of MAX. Fix the failing checks before claiming done.
```

The verifier directive follows immediately after.

## Directive flags

The verifier directive instructs the agent to run:

```
python "<proof.py>" verify
  --transcript "<transcript_path>"
  --root "<cwd>"
  --session "<session_id>"
  --out-dir "<cwd>"
```

- `--session` records the outcome back into the marker store so the blocking
  policy can see whether the claim passed or failed.
- `--out-dir` controls where `proof-report.md` is written (used as receipts on
  re-block).
- `--root` tells the verifier where the project files are (for runner detection
  and config loading).

## Arm / disarm

```bash
python scripts/proof.py arm      # adds Stop hook to .claude/settings.json
python scripts/proof.py disarm   # removes the hook
python scripts/proof.py status   # prints "armed" or "disarmed"
```

All three commands accept `--settings <path>` to target a specific
`settings.json` (defaults to `.claude/settings.json` in the current directory).
