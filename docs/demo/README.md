# Four-provider acceptance fixture

These are the resulting source files from the recorded native build. Run the unchanged acceptance check:

```sh
python3 docs/demo/check.py
```

It exercises inclusive clamping, reversed bounds, division by zero, mean and median over lists and generators, empty inputs, and input preservation. All eight tests pass in the final result.

The [build record](../validation/four-provider-build.json) includes the actual patch, tasks, failures, repair, independent Grok reviews and runtime check evidence. The [verification record](../validation/four-provider-verification.json) identifies the final candidate and integration gates. Codex coordinated; Claude implemented maths.py; Antigravity implemented and repaired stats.py; Grok reviewed independently.

This fixture demonstrates the delivery workflow on a bounded Python task. It does not establish comparative speed, cost or correctness on arbitrary projects. Re-running agents uses each provider's inference service and account access.
