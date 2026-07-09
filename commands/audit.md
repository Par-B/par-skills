---
description: Multi-agent correctness/concurrency/maintainability/performance audit (read-only)
argument-hint: [optional path(s) to scope, e.g. src/network]
allowed-tools: Read, Grep, Glob, Write, Agent, Workflow, Bash(git:*)
model: opus
---
ultracode: Audit this codebase across four dimensions. This is READ-ONLY — do not edit, create, or delete any source files; produce a written report only. If $ARGUMENTS is non-empty, scope the audit to those paths; otherwise audit the primary application/library sources. Exclude build output, dependencies/vendored packages, generated code, and test snapshots/fixtures.

First, orient yourself: detect the language(s), frameworks, build system, and concurrency/threading model in use (read the manifest — e.g. package.json / Cargo.toml / go.mod / pyproject.toml / Package.swift / pom.xml — plus any CLAUDE.md or README). Tailor every dimension below to what you actually find; the bullets are a checklist of what to look for, not an assumption about the stack. Note any strict/opt-in safety settings (e.g. strict null checks, strict concurrency, `-Werror`, linter strictness) and flag findings that would surface under the strictest setting.

Run this as a multi-agent audit: dispatch each of the four dimensions below to its own subagent in parallel via the Workflow tool, then cross-check, de-duplicate, and merge their findings before writing the report. Each subagent is read-only and returns structured findings; the orchestrator synthesizes and writes AUDIT_REPORT.md.

For every finding give: dimension, severity (Critical/High/Medium/Low), file:line, a short evidence snippet, the concrete failure it causes, a suggested fix, and a confidence score. Skip speculative nits. Cross-check findings against each other before reporting, and call out where a fix in one dimension would regress another.

Write the COMPLETE set of findings — every finding, all four dimensions — to AUDIT_REPORT.md. That file is the full record. In your reply to the user, do NOT reproduce the full list: show only the prioritized top-10 (see FINAL OUTPUT), then tell the user the complete report with all findings is in AUDIT_REPORT.md and that they can ask to see them all (or any subset — e.g. by dimension or severity) and you'll surface them from that file.

1. CORRECTNESS
   - Logic errors, off-by-one, wrong boundary conditions
   - Error handling: swallowed/ignored errors, exceptions caught and discarded, error returns not checked, panics/aborts on reachable paths
   - Null/optional/undefined handling: unchecked dereferences, unsafe casts, unhandled empty/none paths
   - Resource lifecycle: connections, sockets, file handles, streams, transactions, or locks not released on error/early-return/cancellation
   - API-contract misuse against the libraries and frameworks the project depends on (wrong argument order, ignored return codes, violated preconditions, misused lifecycle hooks)
   - State/data invariants: mutations that can leave shared or persisted state inconsistent

2. CONCURRENCY / PARALLELISM
   - Data races and unsynchronized access to shared mutable state across threads/tasks/goroutines/coroutines
   - Threading/isolation-model violations for this stack (e.g. UI/main-thread-only work off it, actor/isolation boundaries crossed by non-thread-safe types, unsafe escapes from a safety model)
   - Blocking or long-running synchronous work on a thread that must stay responsive (event loop, UI thread, request handler)
   - async/await, futures, promises, channels: unawaited work, missing cancellation/propagation, tasks that outlive their owner, orphaned operations after teardown
   - Synchronization hazards: deadlocks, lock-ordering inversions, missing/incorrect locking, double-signaled or never-signaled completion primitives (callbacks/continuations/latches resumed zero or multiple times)
   - Lifetime/memory: retain cycles or leaks via captured references in closures/callbacks; observers/timers/subscriptions never torn down

3. MAINTAINABILITY
   - Business logic embedded where it doesn't belong (in UI/view/controller/handler code that should live in a service/model layer); mixed concerns
   - Oversized functions/modules; duplicated logic; leaky abstractions over dependencies
   - State-management misuse for this framework; state held at the wrong layer
   - Naming, dead code, commented-out blocks; missing comments on non-obvious invariants

4. PERFORMANCE
   - Expensive work on a latency-critical path that should be offloaded, cached, or deferred (parsing, serialization, rendering, crypto, large I/O)
   - Redundant recomputation or re-rendering triggered on every state change; work that could be memoized or done once
   - Unnecessary allocations/copies in hot paths; whole-resource loads where streaming/chunking/pagination would do
   - Serialized round-trips (DB/network) that could batch, parallelize, or cache; N+1 patterns

FINAL OUTPUT
Your reply to the user is ONLY the prioritized top-10 list of what to fix first and why — nothing more of the findings. Escalate Critical/High findings from sections 1–2 (correctness & concurrency) to the top of that list. For each top-10 entry, reference the underlying finding(s) by file:line so the user can jump to the full detail in AUDIT_REPORT.md. Close with a one-line count of how many total findings exist (e.g. "37 findings total across 4 dimensions — full report in AUDIT_REPORT.md; ask to see all of them or filter by dimension/severity."). AUDIT_REPORT.md itself always contains the complete, unabridged set organized by dimension and severity, with the same top-10 list at its head.
