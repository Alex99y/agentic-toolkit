# Testing and performance

Load this when the diff touches `_test.go` files, or when explicitly asked
about performance. These items generally need more surrounding context
(benchmarks, profiles, deployment environment) to judge confidently than
the other categories — say so when you're inferring from a diff alone
rather than measured evidence.

## Testing

```go
// Sleeping instead of synchronizing: flaky by construction (either too
// short under load, or needlessly slow when it's long enough to be
// reliable).
go doAsyncThing()
time.Sleep(100 * time.Millisecond)
assertDone(t)
// GOOD — synchronize on the actual event instead of a guessed duration.
done := make(chan struct{})
go func() { doAsyncThing(); close(done) }()
select {
case <-done:
case <-time.After(5 * time.Second):
    t.Fatal("timed out")
}
```

- **Race flag**: this is a CI/tooling concern, not something visible in
  most diffs — only worth mentioning if the diff touches `go test`/CI
  config and `-race` is absent from it.

```go
// BAD — three near-identical copy-pasted test bodies differing only in
// input/expected value; adding a fourth case means copy-pasting again.
func TestAdd(t *testing.T) {
    if Add(1, 2) != 3 { t.Fail() }
}
func TestAddNegative(t *testing.T) {
    if Add(-1, -2) != -3 { t.Fail() }
}
func TestAddZero(t *testing.T) {
    if Add(0, 0) != 0 { t.Fail() }
}

// GOOD — table-driven: a new case is a new row, not a new function.
func TestAdd(t *testing.T) {
    cases := []struct{ a, b, want int }{
        {1, 2, 3}, {-1, -2, -3}, {0, 0, 0},
    }
    for _, c := range cases {
        if got := Add(c.a, c.b); got != c.want {
            t.Errorf("Add(%d,%d) = %d, want %d", c.a, c.b, got, c.want)
        }
    }
}
```

Flag a new test function that's clearly testing the same logic with 3+
near-identical copy-pasted bodies — but don't force existing single-case
tests into table form for no reason.

```go
// BAD — hardcoded time.Now() inside logic under test is flaky near
// boundaries (midnight, month-end) and can never be tested for a
// specific point in time.
func IsExpired(createdAt time.Time) bool {
    return time.Now().Sub(createdAt) > 24*time.Hour
}

// GOOD — an injectable clock makes the time-dependent behavior testable
// with a fixed, deterministic "now".
func IsExpired(createdAt time.Time, now func() time.Time) bool {
    return now().Sub(createdAt) > 24*time.Hour
}
```

Worth a comment when new time-dependent logic has no clock injection
point at all, especially if it's meant to be tested.

```go
// BAD — expensive setup counted in the benchmark's timing, and the
// result is never used, so the compiler may optimize the call away
// entirely (measuring near-zero time for real work).
func BenchmarkProcess(b *testing.B) {
    data := loadLargeFixture() // expensive, shouldn't count
    for i := 0; i < b.N; i++ {
        Process(data)
    }
}

// GOOD — reset the timer after setup, and use the result so it can't be
// optimized away.
func BenchmarkProcess(b *testing.B) {
    data := loadLargeFixture()
    b.ResetTimer()
    var r Result
    for i := 0; i < b.N; i++ {
        r = Process(data)
    }
    _ = r
}
```

## Optimizations

These require the most caution — most are only worth flagging with actual
profiling evidence (`pprof`, benchmarks) rather than instinct, and getting
this category wrong (proposing a "faster" pattern that isn't, or that
sacrifices real readability for a difference too small to matter) does
more harm than skipping it. Reserve inline comments here for cases where
the pattern is unambiguous from the diff alone:

- **Reducing allocations**: an obviously hot path (inner loop of a
  request handler, a function called per-item over a large collection)
  allocating avoidably — e.g. building a `[]byte` via repeated small
  `append`s with no capacity hint where the final size is knowable
  upfront (see data-types-and-strings.md's slice-initialization note), or
  boxing a value into `interface{}` unnecessarily in a loop.
- **Docker/Kubernetes + GOMAXPROCS**: if a diff touches container resource
  limits (a Dockerfile, a Kubernetes manifest's CPU `limits`/`requests`)
  without `GOMAXPROCS` awareness (either `runtime/debug.SetMemLimit`/
  `automaxprocs`, or an explicit `GOMAXPROCS` env var), the Go runtime may
  see the host's full CPU count rather than the container's cgroup limit
  and over-schedule — worth a mention if `uber-go/automaxprocs` (or
  equivalent) isn't already in use.
- **CPU caches, false sharing, instruction-level parallelism, data
  alignment, stack vs. heap, inlining, GC internals**: these need
  profiling data to say anything credible about a specific diff. Don't
  speculate about them from a diff read alone — if something in this
  space looks concerning, say what you'd want to measure to confirm it
  rather than asserting a conclusion.
