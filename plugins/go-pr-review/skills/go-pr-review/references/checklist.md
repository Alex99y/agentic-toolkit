# Go pitfalls checklist

A categorized checklist of common Go mistakes to recognize in a diff — full
attribution for where this list originates is in the plugin's README, not
repeated here since it has no bearing on how to use it.

Each line is a recognition cue, not the full explanation — for the categories
most likely to matter in a real diff, read the matching deep-dive file
(named in parentheses) before writing comments in that area.

## Code and Project Organization (`code-organization-and-api-design.md`)
- Unintended variable shadowing — `:=` inside an `if`/`for` silently shadows an outer variable of the same name (worked example lives in `errors-and-control-flow.md`, since it shows up most often via a shadowed `err`)
- Unnecessary nested code — deep `if`/`else` nesting where early returns would flatten it
- Misusing `init` functions — side effects, error handling you can't control, or ones that make testing/ordering fragile
- Overusing getters and setters — `GetX()`/`SetX()` boilerplate where a plain exported field would do
- Interface pollution — defining interfaces before there are ≥2 real implementations or a real need to decouple
- Interface on the producer side — interfaces should usually live where they're *consumed*, not where they're implemented
- Returning interfaces from functions — prefer returning concrete types; let the caller decide if they need an interface
- `any` says nothing — overuse of `interface{}`/`any` loses the compiler's help; prefer generics or concrete types
- Confusion about when to use generics — generics for algorithms over multiple types; not needed just to avoid one `interface{}`
- Type embedding pitfalls — embedding promotes fields/methods in ways that can leak internals or break encapsulation unexpectedly
- Not using the functional options pattern — long/optional constructor parameter lists that would be clearer as `With...` options
- Project misorganization — package structure that doesn't reflect domain boundaries
- Creating "utility"/"common"/"helpers" packages — dumping-ground packages instead of naming things by what they do
- Ignoring package name collisions — package names that shadow stdlib names or clash on import
- Missing code documentation — exported identifiers without doc comments
- Not using linters — good practice worth a one-line mention if a project's CI has no `go vet`/`gofmt`/`golangci-lint` step at all; this skill doesn't run them itself, it focuses on the judgment calls automated tools can't make

## Data Types (`data-types-and-strings.md`)
- Confusing octal literals — `0755` misread as decimal; prefer `0o755` for clarity
- Neglecting integer overflow — unchecked arithmetic on fixed-width ints, especially from untrusted input
- Not understanding floating-point — `==` comparison on floats, or assuming decimal-exact results
- Confusing slice length and capacity — `len`/`cap` conflated, leading to wrong sizing or unexpected re-allocation
- Inefficient slice initialization — `append` in a loop with no pre-allocated capacity when the size is known upfront
- Confusing nil vs. empty slice — `nil` slice and `[]T{}` behave the same for most ops but differ for JSON/reflect
- Not properly checking if a slice is empty — checking `== nil` instead of `len(s) == 0` (or vice versa when nil-ness matters)
- Not copying slices correctly — `copy()` misuse, or mutating a slice that shares a backing array with another
- Unexpected side effects from `append` — appending to a sub-slice silently mutates the original's backing array
- Slices and memory leaks — retaining a huge backing array via a small sub-slice
- Inefficient map initialization — not using `make(map[K]V, sizeHint)` when the size is known
- Maps and memory leaks — maps only grow; deleting entries doesn't shrink backing memory
- Comparing values incorrectly — `==` on structs/slices/maps/interfaces where it doesn't do what's intended (or `reflect.DeepEqual` misuse)
- `uint` underflow — subtraction between unsigned values that goes negative wraps to a huge positive number instead; the most common real `uint` bug in Go code

## Control Structures (`errors-and-control-flow.md`)
- Elements are copied in range loops — `for _, v := range s` copies each element; mutating `v` doesn't mutate `s`
- How range arguments are evaluated — the range expression (channel, array) is evaluated once, up front
- Impacts of pointer elements in range loops — the classic "loop variable captured by reference" footgun (mostly fixed in Go 1.22+, but check the module's Go version)
- Wrong assumptions during map iteration — iteration order is randomized; inserting during iteration is undefined
- How `break` works — `break` inside a `select`/`switch` nested in a `for` only breaks the inner construct, not the loop
- Using `defer` inside a loop — deferred calls pile up until the *function* returns, not the loop iteration — resource/memory pressure

## Strings (`data-types-and-strings.md`)
- Not understanding `rune` — byte vs. rune vs. grapheme confusion, especially indexing a string by byte position
- Inaccurate string iteration — `for i, c := range s` gives rune, not byte, at non-ASCII positions; naive byte iteration breaks UTF-8
- Misusing `strings.Trim*` — `TrimRight`/`Trim` take a cutset, not a prefix/suffix string (confused with `TrimSuffix`/`TrimPrefix`)
- Under-optimized string concatenation — `+=` in a loop instead of `strings.Builder`
- Useless string/byte conversions — repeated `[]byte(s)`/`string(b)` round-trips that could be avoided
- Substrings and memory leaks — a small substring keeps the entire original string's backing array alive (Go ≤1.19 semantics; less of a concern in the current stdlib, but check)

## Functions and Methods (`functions-methods-stdlib.md`)
- Wrong receiver type — inconsistent or wrong choice between pointer and value receivers
- Never using named result parameters — when they'd meaningfully improve a signature's clarity
- Unintended side effects with named result parameters — naked `return` after mutating a named result inside a `defer`
- Returning a nil pointer as a non-nil interface — the classic "typed nil" bug: `var p *T; return p` as an `error`/interface is never `== nil`
- Not designing for testability at dependency boundaries — a function or struct depends directly on a concrete external dependency (a file path, `*sql.DB`, `*http.Client`, a third-party SDK client) instead of a narrow interface it defines, so every test needs the real thing instead of a fake
- How `defer` arguments/receivers are evaluated — arguments to a deferred call are evaluated *immediately*, not at call time

## Error Management (`errors-and-control-flow.md`)
- Panicking — `panic` for ordinary error handling instead of returning `error`
- Ignoring when to wrap an error — losing context by not using `%w`, or `%w`-wrapping when you shouldn't leak internal errors across a boundary
- Comparing an error type inaccurately — `err.(*MyError)` instead of `errors.As`
- Comparing an error value inaccurately — `err == ErrFoo` instead of `errors.Is` when the error may be wrapped
- Handling an error twice — logging *and* returning the same error up the stack (duplicate reporting)
- Not handling an error — discarded return value (`_ = f()` or ignored entirely) on something that can fail
- Not handling `defer`'s returned error — `defer f.Close()` swallowing a close error that matters (e.g. on writes)
- Custom error type missing `Unwrap()` — wraps another error in a field but doesn't implement `Unwrap() error`, silently breaking `errors.Is`/`errors.As` through it
- Non-idiomatic error message — capitalized or ending in punctuation, awkward once wrapped/concatenated into a larger message
- Returning a non-nil, usable-looking value alongside a non-nil error — invites a caller to skip the error check and use a value that isn't actually valid
- `os.Exit`/`log.Fatal`/`log.Panic` outside `main` — skips all deferred cleanup and takes the decide-whether-this-is-fatal choice away from every caller up the stack

## Concurrency: Foundations (`concurrency.md`)
- Mixing up concurrency and parallelism
- Assuming concurrency is always faster — goroutine/scheduling overhead can lose to sequential code for small workloads
- Confusion about channels vs. mutexes — using the wrong primitive for the job
- Not understanding data races vs. race conditions and the Go memory model
- Ignoring the concurrency impact of workload type — CPU-bound vs. I/O-bound changes the right worker-pool sizing
- Misunderstanding `context.Context` — cancellation, deadlines, and values conflated or misused
- Storing a context in a struct field — pass it explicitly to each method that needs it instead; called out directly in the stdlib's own `context` package doc as something not to do

## Concurrency: Practice (`concurrency.md`)
- Propagating an inappropriate context — e.g. reusing a request context for a background task that must outlive the request
- Starting a goroutine without knowing how/when it stops — goroutine leaks
- Not being careful with goroutines and loop variables — same root cause as the range-loop pointer footgun above, in a concurrent context (much higher-severity there)
- Expecting deterministic behavior from `select` over multiple ready channels — `select` picks pseudo-randomly among ready cases
- Not using notification channels — `chan struct{}` for signaling instead of misusing a data channel
- Not using nil channels — a nil channel blocks forever, which is a deliberate and useful tool (e.g. to disable a `select` case)
- Channel closing discipline — closing an already-closed channel panics, sending on a closed channel panics; only the sender should close, and only once it won't send again
- Being puzzled about channel size — unbuffered vs. buffered semantics, and buffered channels used as a counting semaphore
- Not bounding concurrency with a semaphore where needed — unbounded goroutine fan-out over a shared/expensive resource (DB, downstream API) instead of a buffered-channel or `golang.org/x/sync/semaphore` counting semaphore; a direct extension of the channel-size and errgroup items on this list, worth flagging under the same lens
- Side effects with string formatting — calling a `String()`/`Error()` method concurrently on a type that isn't safe for that
- Data races with `append` — concurrent `append` to a shared slice without synchronization
- Mutexes used inaccurately with slices/maps — locking the mutex but not actually guarding the access, or locking too narrow/wide a scope
- Misusing `sync.WaitGroup` — `Add` called from the wrong goroutine or after `Wait`, or a `WaitGroup` copied by value
- Forgetting `sync.Cond` — polling/sleeping in a loop instead of a proper condition variable
- `sync.Once` marking itself done even if its function panics — a failed one-time initializer silently never retries, leaving callers with partially-initialized state
- Mixing atomic and non-atomic access to the same variable — a plain read/write anywhere races with every `atomic.*` access elsewhere, even though each atomic call is individually safe
- Not using `errgroup` — hand-rolled goroutine+error fan-in instead of `golang.org/x/sync/errgroup`
- Copying a sync type — `sync.Mutex`/`sync.WaitGroup`/etc. copied by value (via struct copy or pass-by-value) instead of by pointer

## Security (`security.md`)
The other of the two highest-value categories, alongside concurrency —
these rarely fail a test suite either, and the consequences when they
reach production are often the most severe on this entire list.
- SQL/command injection — string-built queries or shell commands with non-constant, unparameterized input
- Path traversal — `filepath.Join`/`path.Join` with a request-controlled segment, used to read/write/delete a file, with no check that the result stays inside the intended directory
- Weak randomness for security-sensitive values — `math/rand` used for tokens, session IDs, or secrets instead of `crypto/rand`
- Hardcoded secrets — a literal that looks like a real API key, password, or connection string committed to source
- TLS misconfiguration — `InsecureSkipVerify: true`, or a new `tls.Config` with no `MinVersion` set
- Unbounded request body reads — `io.ReadAll(r.Body)` (or similar) in an HTTP handler with no `http.MaxBytesReader`/size limit, a real DoS vector
- Leaking internal errors externally — `err.Error()` written straight into an HTTP response or API payload instead of logged server-side

## Standard Library (`functions-methods-stdlib.md`)
- Providing a wrong time duration — passing a bare integer where a `time.Duration` is expected (e.g. `time.Sleep(1000)` meaning ms but getting ns)
- `time.After` and memory leaks — called inside a loop/`select`, its timer isn't GC'd until it fires
- Common JSON handling mistakes — struct tags, `interface{}` unmarshal surprises, embedded types
- Common SQL mistakes — forgetting to `Close()` rows, unbounded connection pools, string-built queries
- Not closing transient resources — HTTP response bodies, `sql.Rows`, `os.File` left unclosed
- Never flushing a `bufio.Writer` — closing the underlying file/connection doesn't flush the buffer; silent data loss, not a leak
- Forgetting `return` after replying to an HTTP request — handler keeps executing after `http.Error`/`w.Write`
- Using the default HTTP client/server — no timeouts configured, vulnerable to hanging connections

## Testing (`testing-and-optimization.md`)
- Not categorizing tests — build tags/env vars/short mode to separate unit from integration
- Not enabling the race flag — `go test` without `-race` in CI
- Not using test execution modes — `-parallel`, `-shuffle`
- Not using table-driven tests
- Sleeping in unit tests — `time.Sleep` instead of proper synchronization to wait for async behavior
- Not dealing with the time API efficiently — hardcoding `time.Now()` instead of an injectable clock, making tests flaky/slow
- Not using testing utility packages — `httptest`, `iotest`
- Writing inaccurate benchmarks — not resetting the timer, compiler optimizing away unused results
- Not using fuzzing where it would find real edge cases

## Optimizations (`testing-and-optimization.md`)
Most performance items need profiling evidence to say anything credible
about a specific diff, so this category is deliberately short — see
`testing-and-optimization.md` for why the rest were cut rather than kept
as speculative one-liners.
- Not knowing how to reduce allocations — API design, avoiding unnecessary boxing, `sync.Pool`; the one item here that's often visible directly in a diff (see data-types-and-strings.md's slice-initialization note)
- Not understanding the impact of running Go in Docker/Kubernetes — GOMAXPROCS vs. cgroup CPU limits; visible when a diff touches container resource limits
- Everything else in this space (CPU caches, false sharing, instruction-level parallelism, data alignment, stack vs. heap, inlining, GC internals) — flag only with actual profiling evidence in hand, never from reading a diff alone
