---
type: constraint
---
# Task state
Stored task state comes from several clients. True, 1, and the strings "true", "1", and "yes"
mean complete. False, 0, null, missing values, "false", "0", "no", and an empty string mean active.
String comparisons are case-insensitive and ignore surrounding whitespace.
Use the same interpretation everywhere: lists, summaries, and future export operations.
