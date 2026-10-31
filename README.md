# Documented claim auditor

An offline static tool for auditing documented claims against Python source evidence. It reads the root README.md and Markdown files beneath directories named docs, then parses source with the standard library. Source is never executed. No runtime dependencies, network access, or file writes are needed.

Install and run:

```sh
pip install recommendation-claim-audit
recommendation-claim-audit /path/to/project
python3 -m recommendation_claim_audit /path/to/project --json
```

Use `--verbose` for paths and matched text, repeat `--ignore relative/path` to exclude directory or file prefixes, and use `--fail-on MEDIUM` to fail on evidence found only in tests. The default threshold is HIGH. `--version` prints the package version.

Exit status is 0 when no finding reaches the threshold, 2 when one does, and 1 for usage or I/O errors. JSON contains status, findings, and production and test evidence paths. A MEDIUM finding remains visible even when the exit status is 0.

Fenced blocks are omitted; inline code counts as prose. Matching ignores case, expands negative contractions, replaces hyphens with spaces, and collapses whitespace within paragraphs. Negative spans take precedence. Symlinks are skipped. Source beneath docs, fixtures, and examples is excluded; test evidence is tracked separately. Invalid syntax supplies no evidence.

The static model recognizes imported constructors from Surprise, LightFM, and implicit, including aliases. Bare imports, names without calls, and locally shadowed bindings supply no evidence. This is a narrow syntactic check: it cannot prove runtime behavior, model quality, or that a constructor is reachable. Imports are resolved within a single file, with conservative shadow rejection.

Run tests and build:

```sh
python3 -m unittest discover
python3 -m build
```

Licensed under MIT.
