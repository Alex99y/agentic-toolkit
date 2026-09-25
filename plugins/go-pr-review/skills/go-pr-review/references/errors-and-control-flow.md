# Error management and control structures

## Error comparison and wrapping

The three `errors` package functions exist for a reason — confusing them
is one of the most common real bugs in Go PRs, because the code compiles
and often "works" until an error gets wrapped somewhere upstream and the
comparison silently stops matching.

```go
// BAD — breaks the moment ErrNotFound gets wrapped anywhere upstream.
if err == ErrNotFound { ... }
var myErr *MyError
if e, ok := err.(*MyError); ok { ... }

// GOOD
if errors.Is(err, ErrNotFound) { ... }
var myErr *MyError
if errors.As(err, &myErr) { ... }
```

Wrapping: `fmt.Errorf("doing X: %w", err)` preserves the chain for
`errors.Is`/`errors.As`; `%v` instead of `%w` breaks it. But wrapping isn't
automatically correct either — check whether an internal error is being
wrapped straight through a public API boundary in a way that leaks
implementation details (e.g. a database driver error surfacing in an HTTP
response). That's a judgment call, not a mechanical rule.

```go
// BAD — wraps err inside a custom type but doesn't implement Unwrap(),
// so errors.Is/errors.As can't see past QueryError to whatever it wraps
// — silently breaks the same chain %w is supposed to preserve.
type QueryError struct {
    Query string
    Err   error
}
func (e *QueryError) Error() string { return e.Query + ": " + e.Err.Error() }

// GOOD — Unwrap() lets errors.Is/errors.As traverse through it.
func (e *QueryError) Unwrap() error { return e.Err }
```

Flag a new custom error type (a struct implementing `Error() string`)
that wraps another error in a field but has no `Unwrap() error` method —
it compiles fine and `Error()` reads correctly, but any `errors.Is`/
`errors.As` check against the wrapped error silently stops working the
moment it passes through this type.

Error message convention, worth a quick style check on new error strings:
lowercase, no trailing punctuation (`errors.New("failed to open config")`,
not `"Failed to open config."`) — Go errors are frequently wrapped and
concatenated into larger messages, where a capital letter or a stray
period reads oddly mid-sentence.

## Not handling / double-handling errors

```go
// BAD — error silently discarded.
_ = json.Unmarshal(data, &v)
f, _ := os.Open(path)

// BAD — handled twice: logged here, and the caller will likely log it
// again when it receives the returned error. Pick one.
if err != nil {
    log.Printf("failed: %v", err)
    return err
}
```

An explicitly discarded error (`_ = f()`) is sometimes genuinely fine (a
best-effort `Close()` where nothing can be done about a failure) — but it
should read as a deliberate choice, ideally with a short comment, not a
default. An *implicitly* discarded one (return value never checked at all)
is almost always worth flagging.

```go
// BAD — returns a non-nil *User alongside a non-nil error; a caller that
// forgets to check err first (easy to do, since user "looks" usable) can
// go on to use a partially-populated or garbage value.
func GetUser(id string) (*User, error) {
    u := &User{ID: id}
    if err := db.QueryRow(...).Scan(&u.Name); err != nil {
        return u, err // u is half-populated, not nil
    }
    return u, nil
}

// GOOD — nil value whenever error is non-nil; callers only need to
// check err, which is the convention the rest of the stdlib and
// ecosystem relies on.
func GetUser(id string) (*User, error) {
    u := &User{ID: id}
    if err := db.QueryRow(...).Scan(&u.Name); err != nil {
        return nil, err
    }
    return u, nil
}
```

Flag a function returning a non-nil, apparently-usable value on an
error path — Go's convention is that callers only need to check `err`,
never both; a non-nil value on the error path invites a caller to skip
the error check and use a value that isn't actually valid.

## `defer` pitfalls

```go
// BAD — defer inside a loop: every Close() call piles up until the
// *function* returns, not the loop iteration. In a loop over many files,
// this can exhaust file descriptors before the function ever returns.
for _, path := range paths {
    f, err := os.Open(path)
    if err != nil { return err }
    defer f.Close()
    process(f)
}

// GOOD — wrap the per-iteration work in its own function/scope so defer
// fires each iteration.
for _, path := range paths {
    if err := func() error {
        f, err := os.Open(path)
        if err != nil { return err }
        defer f.Close()
        return process(f)
    }(); err != nil {
        return err
    }
}
```

```go
// BAD — defer'd Close() error is silently dropped, which matters for
// writers (a failed flush/close on write can mean data loss).
defer f.Close()

// BETTER, when the close error matters — capture it into a named return.
func writeFile(path string, data []byte) (err error) {
    f, err := os.Create(path)
    if err != nil { return err }
    defer func() {
        if cerr := f.Close(); err == nil {
            err = cerr
        }
    }()
    _, err = f.Write(data)
    return err
}
```

Deferred call **arguments are evaluated immediately, at the `defer`
statement**, not when the deferred call actually runs:

```go
// Surprising if the author expected `i` to have its final loop value —
// each defer captures the value of i *at defer time*.
for i := 0; i < 3; i++ {
    defer fmt.Println(i) // prints 2, 1, 0 — not 3,3,3 and not 0,1,2
}
```

## Named result parameters

Named results help when a `defer` needs to observe or modify the return
value (see the `Close()` example above) or when the signature is genuinely
clearer for it (e.g. distinguishing several same-typed returns). Used
without that reason, they add a hidden zero-value trap: a naked `return`
after the named result was never explicitly set returns its zero value,
which can silently mask a missing assignment on one code path.

## Range loop footguns

```go
// v is a copy; mutating it does not mutate s.
for _, v := range s {
    v.Field = x // no-op on s itself
}

// Capturing &v or v across iterations by reference is fixed in Go 1.22+
// (per-iteration variable), but still a real bug on modules with an older
// `go` directive in go.mod. Check the module's go.mod before deciding
// whether this is a live bug or already fixed by the toolchain.
var ptrs []*Item
for _, item := range items {
    ptrs = append(ptrs, &item) // pre-1.22: all pointers alias the same var
}

// Map iteration order is randomized by design; code that depends on a
// particular order (including "first" or "last" key) is a bug. Inserting
// into a map while ranging over it is undefined behavior for whether the
// new key is visited.

// break inside a select/switch that's inside a for loop only breaks the
// select/switch, not the enclosing loop. Needs a labeled break.
loop:
for {
    select {
    case <-done:
        break loop // plain `break` here would only exit the select
    }
}
```

## Panics and abrupt termination

`panic` is for programmer errors and truly unrecoverable states (e.g. a
broken invariant at startup), not for ordinary error conditions a caller
should be able to handle — a library function that panics on bad input
instead of returning an `error` forces every caller to either crash or
wrap every call in `recover()`. Flag `panic(` in non-`main`,
non-initialization code as worth a second look, and always flag `panic(`
that's reachable from request-handling code (an HTTP handler, an RPC
method) unless there's a `recover()` upstream that's clearly intentional.

```go
// BAD — os.Exit terminates immediately: no deferred calls run anywhere
// on the goroutine stack (no flushed logs, no closed files, no released
// locks), and the caller of this function has no way to handle the
// failure or decide it's not actually fatal in their context.
func LoadConfig(path string) *Config {
    data, err := os.ReadFile(path)
    if err != nil {
        log.Fatalf("reading config: %v", err) // calls os.Exit(1) internally
    }
    return parse(data)
}

// GOOD — return the error; let the caller (usually only main) decide
// whether it's fatal.
func LoadConfig(path string) (*Config, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return nil, fmt.Errorf("reading config: %w", err)
    }
    return parse(data), nil
}
```

Flag `os.Exit`/`log.Fatal`/`log.Panic` in any function that isn't `main`
(or a `TestMain`/CLI entry point where terminating the process is
genuinely the intended behavior) — both skip deferred cleanup entirely,
and both take the decision to terminate the whole process away from
every caller up the stack, including ones that might have a perfectly
good way to recover.

## Shadowing

```go
// BAD — the inner `err` shadows the outer one; the outer `err` used
// after the if-block is still nil even though the call failed.
var err error
if v, err := doSomething(); err != nil {
    return err
}
// outer err is still nil here — easy to miss in a larger function
```

Most common with `:=` inside an `if`/`for` that reuses a name already
declared in the enclosing scope. `go vet -shadow` (not on by default) or
`golangci-lint`'s `shadow` linter can catch this mechanically if a
project has it enabled in its own CI — but this skill doesn't run those
tools itself, so don't assume it's already covered; read for it directly.
