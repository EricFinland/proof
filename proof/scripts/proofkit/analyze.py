"""Run diff-based analyzers for a claim. Analyzer errors never affect verdicts."""
from proofkit.strategies.base import DEFAULT_COMMAND_TIMEOUT

REPRO_HINT = ("no repro found for this fix claim; add or change a test, or include a "
              "line Repro: `<command>` that failed before the fix")


def run_analyzers(msg, claims, root, cfg, changes, budget, marker_root=None,
                  command_timeout=DEFAULT_COMMAND_TIMEOUT):
    results, notes = [], []
    if changes is None:
        notes.append("no git baseline: tamper, scope, and redgreen checks skipped")
        return results, notes
    from proofkit.baseline import Unresolved
    if isinstance(changes, Unresolved):
        notes.append(changes.note)
        return results, notes
    if changes.approximate:
        notes.append("baseline: HEAD (approximate)")
    strategies = {c.strategy for c in claims}

    def _safe(name, fn):
        try:
            r = fn()
            if r is not None:
                results.append(r)
        except Exception as e:  # never let analysis break verification
            notes.append(f"{name} analysis skipped: {e}")

    if strategies & {"tests", "build"}:
        from proofkit import tamper
        _safe("tamper", lambda: tamper.to_result(msg, tamper.analyze(changes, root, cfg)))
    from proofkit import scope
    _safe("scope", lambda: scope.to_result(msg, scope.analyze(msg, changes, root)))
    from proofkit.classifier import is_fix_claim
    if is_fix_claim(msg) and not changes.approximate:
        from proofkit import redgreen
        try:
            spec = redgreen.find_repro(msg, changes, root, cfg)
        except Exception as e:  # never let analysis break verification
            spec = False
            notes.append(f"redgreen analysis skipped: {e}")
        if spec is None:
            notes.append(REPRO_HINT)
        elif spec:
            _safe("redgreen", lambda: redgreen.run(msg, spec, root, changes.base_commit,
                                                   budget, marker_root=marker_root,
                                                   command_timeout=command_timeout))
    return results, notes
