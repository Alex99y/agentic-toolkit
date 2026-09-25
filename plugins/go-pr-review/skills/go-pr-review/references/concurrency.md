# Concurrency deep dive — goroutines, channels, mutexes, semaphores

This is one of the two highest-value categories to review carefully
(security, in `security.md`, is the other). A data race or a goroutine
leak almost never fails `go vet`, almost never shows up in a unit test,
and often doesn't manifest until the code is under real production load
— which means a PR reviewer reading the diff by eye is sometimes the
*only* check that catches it before it ships. Slow down here.

## Goroutine lifecycle

Every `go func(...)` you see in a diff, ask: **how and when does this
goroutine stop?** If the answer isn't obvious from reading the function,
that's a leak waiting to happen — the goroutine (and everything it's
holding onto: buffers, closures, connections) lives until the process
exits.

```go
// BAD — this goroutine never stops, even after the caller stops caring.
func startWatcher(ch <-chan Event) {
    go func() {
        for e := range ch {
            handle(e)
        }
    }()
}

// GOOD — the goroutine exits when the context is cancelled.
func startWatcher(ctx context.Context, ch <-chan Event) {
    go func() {
        for {
            select {
            case <-ctx.Done():
                return
            case e := <-ch:
                handle(e)
            }
        }
    }()
}
```

Loop-variable capture: in Go 1.22+, `for _, v := range s` gives each
iteration its own `v`, so the classic
`for _, item := range items { go func() { use(item) }() }` bug is fixed at
the language level. **Check the module's `go` directive in `go.mod`**
before assuming this — a pre-1.22 module (or one that hasn't bumped the
directive even on a newer toolchain) still has the bug, and it's much more
dangerous here than in the sequential-loop version of this same footgun,
because the goroutines actually run concurrently with the loop rather than
after it.

## Channels

- **`select` over multiple ready channels is not first-come-first-served.**
  If more than one `case` is ready, Go picks pseudo-randomly. Code that
  assumes a specific case "wins" when several channels fire close together
  has a latent bug.
- **Notification channels:** `chan struct{}` (zero-width) is the idiomatic
  way to signal "something happened" without carrying data. Seeing a
  `chan bool` or `chan int` used purely as a signal, where the value is
  never read, is a sign the author reached for the wrong tool — flag as
  style, not a bug.
- **Nil channels are a feature, not a mistake by default** — a nil
  channel blocks forever in a `select`, which is the standard way to
  disable a case dynamically (e.g. set a channel to `nil` after its first
  event to stop selecting it again). Don't flag `var ch chan T` or
  `ch = nil` as a bug without checking whether that's the intent.
- **Channel size and semaphores:** an unbuffered channel synchronizes; a
  buffered channel of size N also acts as a counting semaphore — if you
  see a pattern fanning out goroutines over a limited resource (DB
  connections, an external API, disk I/O) with **no** bound, that's a real
  capacity/stability risk, not just style:

```go
// BAD — unbounded fan-out; N concurrent requests can overwhelm downstream.
for _, id := range ids {
    go func(id string) {
        results <- fetch(id)
    }(id)
}

// GOOD — buffered channel of size N as a counting semaphore.
sem := make(chan struct{}, 10)
for _, id := range ids {
    sem <- struct{}{}
    go func(id string) {
        defer func() { <-sem }()
        results <- fetch(id)
    }(id)
}

// GOOD — same idea via golang.org/x/sync/semaphore for weighted acquires,
// or via errgroup.SetLimit (Go 1.20+) when you're already using errgroup.
g, ctx := errgroup.WithContext(ctx)
g.SetLimit(10)
for _, id := range ids {
    id := id
    g.Go(func() error { return fetch(ctx, id) })
}
```

## Channel closing discipline

Three rules, and violating any of them panics at runtime rather than
failing at compile time:

```go
ch := make(chan int)
close(ch)
close(ch)       // panic: close of closed channel
ch <- 1         // panic: send on closed channel
v, ok := <-ch   // fine — reading a closed channel returns the zero value
                // and ok == false, draining it doesn't panic
```

The convention that avoids all three: **only the sender closes a
channel, and only once it will never send on it again.** Flag a diff
where a receiver closes a channel it doesn't own, where multiple
goroutines could plausibly call `close()` on the same channel without
coordination, or where a channel might be closed and then have a send
attempted on it from another code path — all three are real panics
waiting for the right timing, not just style concerns.

## Mutexes

- **Channels vs. mutexes:** mutexes guard *shared state*; channels
  communicate *ownership transfer or events*. Seeing a mutex used to
  serialize access to a channel, or a channel used purely to protect a
  struct field two goroutines both mutate directly, is usually the wrong
  primitive for the job.
- **Guard scope:** the mutex must actually cover every access to the
  state it protects — including reads. A struct with a `mu sync.Mutex`
  field and *some* methods that lock and others that don't (especially
  read-only-looking getters) is a data race, not a stylistic
  inconsistency.

```go
// BAD — Get doesn't lock, so it races with concurrent Set calls.
type Cache struct {
    mu sync.Mutex
    m  map[string]string
}
func (c *Cache) Set(k, v string) {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.m[k] = v
}
func (c *Cache) Get(k string) string {
    return c.m[k] // <-- unguarded read, races with Set
}
```

- **Copying a `sync.Mutex` (or anything containing one — `WaitGroup`,
  `Once`, etc.) copies its state.** `go vet` catches this (`copylocks`),
  but confirm it's actually run in the project's toolchain before
  assuming it will. Passing a struct with a mutex field *by value* into a
  function, or ranging over a `[]structWithMutex` by value, are the
  common ways this slips in.

## `sync.WaitGroup` and `sync.Cond`

```go
// BAD — Add() called inside the goroutine races with Wait() in the parent;
// Wait() can return before all goroutines have even called Add().
func run(tasks []Task) {
    var wg sync.WaitGroup
    for _, t := range tasks {
        go func(t Task) {
            wg.Add(1)
            defer wg.Done()
            t.Run()
        }(t)
    }
    wg.Wait()
}

// GOOD — Add() happens in the loop, before the goroutine starts.
func run(tasks []Task) {
    var wg sync.WaitGroup
    for _, t := range tasks {
        wg.Add(1)
        go func(t Task) {
            defer wg.Done()
            t.Run()
        }(t)
    }
    wg.Wait()
}
```

`sync.Cond` is rare in application code, but if you see a goroutine
polling a condition in a `for { ...; time.Sleep(x) }` loop where it's
actually waiting on another goroutine to change shared state, that's
exactly what `sync.Cond` (or a channel) exists to replace — flag it as a
missed idiom, and note the polling also wastes CPU and adds latency.

## `sync.Once`

```go
var once sync.Once
var client *Client

func getClient() *Client {
    once.Do(func() {
        client = newClient() // if this panics...
    })
    return client // ...once still marks itself done, client stays nil forever
}
```

`sync.Once` marks itself "done" as soon as the function passed to `Do`
returns — including by panicking. A panicking initializer doesn't get
retried on the next call; `Do` silently becomes a no-op from then on,
and callers get back whatever partially-initialized state existed at the
panic. Worth a comment whenever `once.Do(...)`'s function can fail (calls
something fallible, isn't trivially side-effect-free) with no recovery
or retry path — the fix is usually making the initializer itself
infallible, or checking the result explicitly rather than trusting
`Once` to enforce success.

## Atomic vs. mutex-guarded access

```go
type Counter struct {
    n int64
}
func (c *Counter) Inc() {
    atomic.AddInt64(&c.n, 1)
}
// BAD — reads c.n directly instead of atomic.LoadInt64(&c.n); racing
// with concurrent Inc() calls even though Inc() itself is atomic.
func (c *Counter) Value() int64 {
    return c.n
}
```

Every access to a variable that's ever touched via the `sync/atomic`
package (or `atomic.Int64`/`atomic.Bool`/etc. types) needs to go through
`atomic` — a single plain read or write anywhere else is a data race with
every atomic access elsewhere, even though each individual atomic call is
"safe" in isolation. Flag a struct field written via `atomic.Add*`/
`atomic.Store*` (or an `atomic.*` typed field) that's read anywhere
without the matching `atomic.Load*`/method call.

## `errgroup`

If a diff hand-rolls "start N goroutines, collect the first error, wait
for all of them" — that's what `golang.org/x/sync/errgroup` is for:

```go
// Hand-rolled — works, but every caller of this pattern re-implements
// the same error-collection and must remember the mutex.
var wg sync.WaitGroup
var mu sync.Mutex
var firstErr error
for _, u := range urls {
    wg.Add(1)
    go func(u string) {
        defer wg.Done()
        if err := fetch(u); err != nil {
            mu.Lock()
            if firstErr == nil {
                firstErr = err
            }
            mu.Unlock()
        }
    }(u)
}
wg.Wait()

// GOOD — errgroup does the same thing, plus cancels sibling goroutines
// via ctx as soon as one returns an error.
g, ctx := errgroup.WithContext(ctx)
for _, u := range urls {
    u := u
    g.Go(func() error { return fetch(ctx, u) })
}
err := g.Wait() // first non-nil error, or nil
```

Not wrong to hand-roll it, but worth a style comment: `errgroup` also
gives you `SetLimit` (see the semaphore example above) for free.

## Data races beyond mutexes

`append` on a slice that's shared across goroutines without synchronization
is a data race even though nothing "looks like" shared mutable state at
the call site — `append` may reallocate and write to the backing array,
and two goroutines racing on that write is exactly the race detector's
target case.

```go
// BAD — concurrent append to the same slice from multiple goroutines.
var results []int
var wg sync.WaitGroup
for _, n := range nums {
    wg.Add(1)
    go func(n int) {
        defer wg.Done()
        results = append(results, process(n)) // race
    }(n)
}
```

If you have any doubt about whether a pattern races, say so honestly
rather than asserting confidently either way — and if the project runs
`go test -race` in CI, mention that as the authoritative way to settle
it, since static reading can miss races that the detector catches at
runtime (and vice versa: catches only races actually exercised by test
execution).

## Context

```go
// BAD — ctx.Value used to smuggle an optional parameter past the
// signature instead of just adding it; nothing about the function
// signature tells a caller this dependency exists.
func Process(ctx context.Context, item Item) error {
    dryRun, _ := ctx.Value(dryRunKey).(bool)
    // ...
}

// GOOD — context.Value reserved for things that must cut across API
// boundaries the caller doesn't control (request IDs, auth), everything
// else is an explicit parameter.
func Process(ctx context.Context, item Item, dryRun bool) error { ... }
```

```go
// BAD — handler fires background work using the request's own context;
// that context is cancelled the instant the handler returns, so the
// "background" work is silently killed almost immediately.
func handler(w http.ResponseWriter, r *http.Request) {
    go sendWebhook(r.Context(), payload) // cancelled when handler returns
    w.WriteHeader(http.StatusAccepted)
}

// GOOD — a context whose lifetime doesn't end with the request.
func handler(w http.ResponseWriter, r *http.Request) {
    go sendWebhook(context.WithoutCancel(r.Context()), payload)
    w.WriteHeader(http.StatusAccepted)
}
```

```go
// BAD — a context stored as a struct field. It's unclear from the
// struct's construction how stale or long-lived this context is by the
// time any method runs, and every caller of a method on s now depends on
// a context they didn't pass in and may not know exists.
type Server struct {
    ctx context.Context
}

// GOOD — pass context explicitly to each method that needs it, as the
// first parameter, named ctx. This is explicit enough that it's called
// out directly in the standard library's own context package doc.
type Server struct{}
func (s *Server) Handle(ctx context.Context, req Request) error { ... }
```

## String formatting side effects

```go
type Stats struct {
    mu    sync.Mutex
    count int
}
func (s *Stats) Inc() {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.count++
}
// BAD — String() reads s.count without the lock Inc() uses to write it;
// concurrent fmt.Sprintf("%v", stats) / log.Println(stats) races with Inc.
func (s *Stats) String() string {
    return fmt.Sprintf("count=%d", s.count)
}
```

This is easy to miss in review because the call site (`log.Println(x)`,
`fmt.Sprintf("%v", x)`) doesn't look like it's touching shared state at
all — the race is hidden inside `x`'s own `String()`/`Error()`/`Format()`
method. Worth a specific check whenever a type with a mutex-guarded field
also defines one of those methods without taking the same lock.
