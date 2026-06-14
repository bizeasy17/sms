# UAT Agent Instruction Harness

## Mission
- This workspace is the lab UAT environment.
- Focus on safe validation, reproducible checks, and minimal-risk changes.
- Keep responses concise and token-efficient by default; return only necessary key points unless detailed output is explicitly requested.

## Guardrails
- Never add or enable auto-trading execution behavior.
- Never expose secrets, tokens, or credentials in code, logs, or docs.
- Keep edits scoped to the requested task; avoid unrelated refactors.
- Default Python runtime for commands/checks/tests is `c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe` unless the task explicitly requires another environment.
- Prefer brief command output summaries over verbose logs to reduce token usage.
- Prefer reversible, low-risk changes first; document behavior changes.
- Do not run destructive cleanup (drop/truncate/delete-all) without explicit user approval.
- Before changing API behavior, state the exact contract impact and get confirmation.
- For multi-service changes, verify upstream to downstream in order.

## UAT Change Workflow
1. Confirm target service and ownership before coding.
2. Prepare a short requirement note for functional changes.
3. Implement minimal patch only.
4. Run validation commands and capture pass/fail.
5. Summarize impacted files and runtime verification steps.

## Validation Rules
- Prefer service-level smoke tests over broad data mutations.
- Use deterministic commands and keep logs concise.
- If a check cannot be run, state it explicitly with reason.

## Data Safety
- Do not overwrite historical snapshots/baselines unless explicitly requested.
- Prefer side-by-side outputs for comparison before replacing existing artifacts.
- Keep rollback path clear for any UAT data write operation.

## Delivery
- Report: changed files, test commands, and key results.
- Ask whether to commit/push after validation passes.
