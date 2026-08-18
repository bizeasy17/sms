# UAT Optimization Documents

Store all UAT optimization-related documents in this directory, including
requirements, technical designs, performance investigations, validation records,
and rollout or rollback notes.

## Current Optimization Instruction

For this optimization, preserve existing frontend components and backend business
logic without modification. Implement approved optimization proposals by creating
new frontend and backend code files that reuse the existing components and
business logic. Do not replace, edit, or delete the current implementation unless
the user explicitly authorizes an exception.

Mount every newly generated optimization page and its frontend request endpoints
under an `/opt/...` URL prefix. Do not attach new optimization behavior to an
existing non-`/opt` URL.

Use this naming convention:

`<AREA>_<TOPIC>_<YYYYMMDD>.md`

Examples:

- `VALUATION_QUICK_VIEW_PERFORMANCE_20260818.md`
- `VALUATION_STOCK_PICKING_UI_20260818.md`
- `VALUATION_PREFILL_VALIDATION_20260818.md`

Each optimization document should state the target surface, problem or goal,
scope, proposed change, interface or database contract impact, validation method,
and result. Record rollback steps for any change that affects scheduled tasks or
persisted data.