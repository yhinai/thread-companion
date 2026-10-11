# Thread transfer evaluation

Status: **complete**
Storage: `mongodb-atlas` · Agent: `codex` · Model: `inherited Codex configuration`

Base commit: `2e0dba4e5e3ffd6e02311d659a41d8715462865d`
Grader: `d19045b5b830dfc4c160d2fcf572c55e8568db3796f5381a467c9faf9b8c78b3`

Fixture: `isolated_unimplemented`

one fresh agent invocation per arm/task/repeat; same repository commit and task prompt; token use measured, not equalized

| Context | Tasks passed | Seconds | Input tokens | Output tokens |
|---|---:|---:|---:|---:|
| no_memory | 0/6 | 281.16 | 616033 | 3190 |
| current_notes | 6/6 | 172.89 | 462662 | 5605 |
| notes_and_skill | 6/6 | 182.83 | 428065 | 5501 |

## Interpretation

This is a small, custom demonstration, not a general agent benchmark. Compare current_notes with notes_and_skill to estimate the incremental effect of a learned skill; no_memory also measures access to project-specific requirements. More tokens or time can explain differences. Equal results are not evidence of a skill benefit. Trial order is randomized and raw results are preserved. The same base commit, task prompt, grader and agent configuration are used across arms. Repository/provider instructions may still supply background knowledge. Prompt isolation is not a security boundary.
