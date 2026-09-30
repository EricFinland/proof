# Hook Setup, Pending Enforcement, and the Chain Cap

`proof arm` installs two hooks into `.claude/settings.json`. Both commands use
quoted absolute paths:

```
"<python-interpreter>" "<absolute path to proof_session_start.py>"
"<python-interpreter>" "<absolute path to proof_trigger.py>"
```

For example, on a typical install:
```
"C:\Python314\python.exe" "C:\Users\you\.claude\skills\proof\scripts\proof_trigger.py"
```

The written entries look like this:

```json
{
  "hooks": {
    "Stop": [
      {"hooks": [{"type": "command", "command": "\"python\" \".../proof_trigger.py\"", "timeout": 120}]}
    ],
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "\"python\" \".../proof_session_start.py\"", "timeout": 30}]}
    ]
  }
}
```

Re-running `arm` replaces Proof's own entries and leaves every other hook alone.
`disarm` removes both.

Both hooks never raise and never print anything except their JSON output. An
error inside Proof lets the turn end normally.

## SessionStart hook

`proof_session_start.py` reads `{session_id, cwd}` from stdin and captures a
baseline for the session:

1. `git add -A` into a temporary index file and `git write-tree`, so the tree
   includes tracked and untracked files and excludes anything git ignores. Your
   real index and working tree are untouched.
2. `git commit-tree` on that tree, parented on `HEAD`.
3. `git update-ref refs/proof/baseline/<session> <commit>` so garbage collection
   keeps it. The commit holds copies of untracked files and appears in
   `git log --all` until it is pruned.
4. A record in `$PROOF_HOME/baselines/<session>.json` (default `~/.proof`).
5. Baseline refs and records older than 7 days are pruned.

A second SessionStart for the same session (a resume) keeps the first baseline.
Outside a git repository nothing is captured. Set `[baseline] enabled = false`
to skip capture; the analyzers then fall back to `HEAD` as an approximate
baseline.

The SessionStart timeout is 30 seconds.

## Stop hook timeout

The Stop hook runs checks in-process, so it needs more time than a plain
classifier would. `arm` sets its `timeout` to `inline_budget + 30` seconds
(120 with the default budget of 90). The extra 30 seconds covers analysis,
report writing, and interpreter startup. `PROOF_INLINE_BUDGET` is honored when
computing it. Re-run `arm` after changing `[verify].inline_budget`.

## Stop hook flow

The hook reads `{session_id, transcript_path, stop_hook_active}` from stdin.

**Fresh stop** (`stop_hook_active` is false: the agent stopped on its own):

1. Reset the session's continuation chain.
2. Read the agent's last message. If the classifier finds no completion claim,
   or the per-claim blocking policy says no (below), let the turn end.
3. If cost gating is enabled and says skip, let the turn end (see `gating.md`).
4. Record the attempt, store the claim text under its `claim_key`, and bump the
   chain count.
5. Run the claim's checks and the diff analyzers inline under the budget, then
   decide:

| Result | Hook output |
|---|---|
| Any FAIL | Block. The reason is the failing command and the tail of its output (the receipt), labeled "attempt N of MAX". No subagent. |
| SUSPECT, findings not seen before this session | Block once with the findings and ask the agent to revert or explain. |
| SUSPECT, same findings already shown | No block for the findings. A `systemMessage` lists them for the user. |
| Deferred or INCONCLUSIVE checks remain | Mark the claim `pending` with those strategies and block with a subagent directive. |
| No checkable claim at all ("all done") | Mark it `pending` as "unstructured claim" and block with a subagent directive. |
| Everything resolved and PASS | No block. A `systemMessage` such as `Proof: PASS (build, tests)`. |

When the claim is a fix and no repro source exists, block reasons end with a
hint asking for a changed test or a ``Repro: `<command>` `` line.

**Continuation stop** (`stop_hook_active` is true: the agent is stopping again
after Proof blocked it):

1. If the chain has reached `max_fix_cycles` blocks, let the turn end.
2. If the session has a `pending` claim, enforce it (below).
3. Otherwise, if the chain's last verdict was `fail` or `suspect`, the agent is in
   the fix loop: a new completion claim is verified again, even if it is worded
   differently, and the cost gate is never consulted.
4. Otherwise let the turn end.

## Why stop_hook_active no longer short-circuits

In v2 the hook returned immediately whenever `stop_hook_active` was set. That
stopped infinite loops, but it also meant an agent could ignore the verifier
directive and simply stop again. The second stop arrived with
`stop_hook_active: true` and the claim went unverified.

In v3 the flag marks a continuation chain instead. The hook still refuses to
loop forever, but the guard is the chain cap, not the flag. This lets Proof
enforce a pending verification and keep the fix loop going inside one chain.

## Pending enforcement

A pending claim can only be cleared by `proof.py verify --session <id>
--claim-key <key>`, which records a verdict for that key. Agent prose never
clears it. On a continuation stop with a claim still pending, the hook blocks
again:

```
PROOF: verification was not run. The claim is still pending. PROOF: you claimed
work is complete. These checks still need an independent verifier: ...
```

Each of these re-blocks counts as an attempt on the claim and a block in the
chain. When the claim reaches `max_fix_cycles` attempts, or the chain reaches
`max_fix_cycles` blocks, the hook lets the turn end with a message that the claim
was never verified.

Only one claim per session is pending at a time. A newer pending claim demotes
the older one, and a new turn clears it, so a verifier left unrun in one turn is
never demanded in the next.

## Chain cap

A chain is the run of stops from one fresh stop until Proof stops blocking.
Every block in it counts: FAIL receipts, SUSPECT blocks, subagent directives, and
"verification was not run" re-blocks. With the default `max_fix_cycles = 3`, the
agent gets at most three blocks before the turn is allowed to end. The count
labels FAIL receipts ("attempt 2 of 3"), even when the agent rewords its claim.

On the last slot of a chain, a first-time SUSPECT is not blocked, because no
later stop could show the findings to the user. It goes out as a
`systemMessage` right away.

## Per-claim blocking policy

Tracked in `$PROOF_HOME/verified.json`, keyed by `(session_id, claim_key)`
where `claim_key` is a hash prefix of the claim text.

| State | Action |
|-------|--------|
| Claim never seen in this session | Verify. |
| Last outcome `pass` | Never re-block. |
| Last outcome `inconclusive` | Never re-block. |
| Last outcome `fail`, `suspect`, or `pending`, attempts < `max_fix_cycles` | Verify again. |
| Attempts >= `max_fix_cycles` | Let the turn end. |

`max_fix_cycles` defaults to `3` and can be overridden in `.proof.toml`:

```toml
[verify]
max_fix_cycles = 5
```

## Directive flags

The subagent directive instructs the agent to run:

```
python "<proof.py>" verify
  --transcript "<transcript_path>"
  --root "<cwd>"
  --session "<session_id>"
  --claim-key "<claim_key>"
  --out-dir "<cwd>"
```

- `--claim-key` makes `verify` load the stored claim text instead of the
  transcript's last message, which after a block is usually "I'll spawn a
  verifier", not the claim.
- `--session` records the outcome back into the marker store, which clears
  `pending` and tells the next stop how the claim did.
- `--out-dir` controls where `proof-report.md` is written.
- `--root` tells the verifier where the project files are (for runner detection
  and config loading).

The agent may run `proof.py verify` itself instead of spawning a subagent. That
is acceptable: the receipt comes from the same deterministic code either way.

## Arm / disarm

```bash
python scripts/proof.py arm      # adds the Stop and SessionStart hooks
python scripts/proof.py disarm   # removes both
python scripts/proof.py status   # prints "armed" or "disarmed"
```

All three commands accept `--settings <path>` to target a specific
`settings.json` (defaults to `.claude/settings.json` in the current directory).
