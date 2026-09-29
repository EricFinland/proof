"""Run diff-based analyzers for a claim. Analyzer errors never affect verdicts."""


def run_analyzers(msg, claims, root, cfg, changes, budget, marker_root=None):
    results, notes = [], []
    if changes is None:
        notes.append("no git baseline: tamper, scope, and redgreen checks skipped")
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
    from proofkit.classifier import is_change_claim
    if is_change_claim(msg):
        from proofkit import scope
        _safe("scope", lambda: scope.to_result(msg, scope.analyze(msg, changes)))
    # Task 11 adds redgreen here.
    return results, notes
