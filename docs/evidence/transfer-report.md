# Thread transfer evaluation

Status: **complete**
Storage: `mongodb-atlas` · Agent: `codex` · Model: `inherited Codex configuration`

Base commit: `fb719381b6c588f191e11a7b9715583b2145b24b`
Grader: `d19045b5b830dfc4c160d2fcf572c55e8568db3796f5381a467c9faf9b8c78b3`

one fresh agent invocation per arm/task/repeat; same repository commit and task prompt; token use measured, not equalized

| Context | Tasks passed | Seconds | Input tokens | Output tokens |
|---|---:|---:|---:|---:|
| no_memory | 6/6 | 142.14 | 447414 | 4151 |
| current_notes | 6/6 | 175.97 | 518258 | 5522 |
| notes_and_skill | 6/6 | 180.62 | 522308 | 5371 |

## Interpretation

This is a small, custom demonstration, not a general agent benchmark. Compare current_notes with notes_and_skill to estimate the incremental effect of a learned skill; no_memory also measures access to project-specific requirements. More tokens or time can explain differences. Equal results are not evidence of a skill benefit. Trial order is randomized and raw results are preserved. The same base commit, task prompt, grader and agent configuration are used across arms. Repository/provider instructions may still supply background knowledge. Prompt isolation is not a security boundary.
