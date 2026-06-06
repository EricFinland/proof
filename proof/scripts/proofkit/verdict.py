def aggregate(results):
    verdicts = [r.verdict for r in results]
    if "fail" in verdicts:
        return "fail"
    if "pass" in verdicts:
        return "pass"
    return "inconclusive"
