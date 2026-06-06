# claude-skill

A collection of Claude Code skills built for agent reliability.

## proof/

Proof is a Stop hook and independent verifier that catches hallucinated
completion claims. When an agent says "tests pass" or "all done, it works",
Proof fires a separate verifier that runs the real checks and returns a
strict PASS/FAIL/INCONCLUSIVE verdict with receipts.

See [proof/README.md](proof/README.md) for full documentation, install
instructions, and the 10-second demo.
