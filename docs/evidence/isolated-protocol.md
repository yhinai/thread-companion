# Isolated implementation comparison

This follow-up addresses a limitation of the original comparison: every arm could reuse the corrected completion interpreter already present in the repository. The original 18 tied trials remain published.

The follow-up uses a new repository with one commit, two unimplemented operations, no tests containing state examples, and no previous implementation or Git history. All arms receive that same repository. The project notes and learned procedure are frozen once before the first trial. No new lesson is authored for this comparison.

- Same two tasks, existing external grader, model configuration, and three context conditions as the original comparison.
- Three repeats per task and condition: 18 real fresh Codex invocations, with order randomized using seed 17.
- The grader is fingerprinted before and after each trial. Trial prompts prohibit accessing external vaults, earlier runs, benchmark files, or grader implementations. Prompt isolation is not a security boundary.
- Trial results, patches, wall time, and token use are retained in Atlas. All completed trials are reported, including failures. No prompt, criterion, or task changes are made in response to interim results.
- The no-memory condition lacks the project's authored completion convention. A difference against current notes therefore measures access to requirements, not superior reasoning. Only current notes versus notes plus skill measures the incremental effect of the learned procedure.
- Three repeats on a small fixture do not establish generalization or statistical significance. Equal results do not demonstrate procedural benefit. Time and token use are measured, not equalized.

Run after completing the existing learning proof and stopping its coordinator:

```sh
bash scripts/atlas.sh proof evaluate-isolated --root .thread/atlas-proof --repeats 3
```

The command refuses to overwrite an existing isolated fixture. The original proof repository, memories, grader, and published results are preserved.
