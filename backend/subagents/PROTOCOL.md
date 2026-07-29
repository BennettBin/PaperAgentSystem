# Multi-Agent Role Protocol v1

This protocol constrains the optional collaboration layer. It does not replace the existing single-Agent runtime or public API.

## Data ownership

Each artifact has exactly one producing role as its owner and an immutable version. Agents exchange only `ArtifactRef` and `DataRef` values inside a validated `MessageEnvelope`; raw prompts, private chain-of-thought, and hidden reasoning are never routed. Consumers may create a new version but may not mutate an artifact owned by another role. Workspace identifiers are mandatory and cross-workspace reads fail closed.

## Conflict semantics

Conflicting findings are retained as separately owned artifacts. The Coordinator records the conflict and routes both references to Critic or Verifier; it must not silently choose one. Verifier gives the terminal evidence decision, while unresolved conflicts produce an explicit failed or degraded result.

## Timeout and retry semantics

Every role has a deadline and bounded budget in its Manifest. A timed-out call may retry at most once when its policy is `retry_once`; the second attempt keeps the same task and idempotency identity and sets `attempt` to 2. Optional roles may degrade, while unavailable required roles fail explicitly. Retrying cannot expand the Tool whitelist or token, step, and Tool-call budgets.

## Cancellation semantics

Cancellation propagates from Coordinator to all active role assignments through a `cancel` envelope. A cancelled role must stop before another Tool call, preserve already committed artifacts, and emit no new result artifact. Late results are ignored and cannot reopen a terminal task.

## Coordination boundaries

Only Coordinator schedules roles. Child roles cannot message the user, recursively spawn agents, or dispatch another role. All Tool calls are checked against the role Manifest whitelist. Critic is optional and may be skipped with a labelled degraded output; Coordinator, Paper Reader, Evidence, Writer, and Verifier are required and their absence causes explicit failure.

## Writer citation and degradation semantics

Writer citations parsed from the user-visible answer are canonical. The runtime accepts single, grouped, and full-width Evidence Matrix citations, normalizes the redundant declared citation list, and never treats a mismatched list alone as a reason to discard an otherwise valid answer. Unknown citations, missing readable-paper coverage, undisclosed unreadable papers, or unresolved Critic issues permit exactly one targeted Writer repair with the validation difference. If repair fails, deterministic evidence-only degradation is allowed only when every assigned paper is readable, the Evidence Matrix has no conflicts, Critic has no severe issue, and every paper has at least one non-inferred Claim backed by same-paper source evidence. The degraded draft is labelled, contains no new synthesis, and must still pass Verifier; otherwise the required Writer path fails explicitly.

Paper Reader evidence identifiers are not trusted directly from model output. The runtime maps a quote to a unique same-paper retrieval hit and rewrites its Chunk/Page provenance; when a safe unique mapping is unavailable, it uses bounded raw retrieval hits from that paper instead of inventing an identifier. A deterministic Verifier override is permitted only for the byte-for-byte canonical evidence-only draft regenerated from the current validated Matrix, after all strict degradation predicates and deterministic citation/coverage/number checks pass. This override handles invalid model-verifier structure or the narrow false-positive case where separately cited per-paper facts are labelled as an unsupported cross-paper inference; it never applies to arbitrary generated prose.
