# Functions, methods, and standard library pitfalls

## Receiver choice

```go
// BAD — Set uses a pointer receiver (mutates the real struct), Get uses
// a value receiver (operates on a throwaway copy). Both compile; a
// caller holding a Cache value instead of *Cache silently never sees
// Set's writes at all, since Set was called on a copy.
type Cache struct {
    mu sync.Mutex
    m  map[string]string
}
func (c *Cache) Set(k, v string) { c.mu.Lock(); defer c.mu.Unlock(); c.m[k] = v }
func (c Cache) Get(k string) string { return c.m[k] } // value receiver — inconsistent
```

Mixing pointer and value receivers across the same type's methods is the
thing to flag — not pointer-vs-value in isolation. Also flag a value
receiver on a type that contains a mutex or other no-copy field (see
concurrency.md's note on copying sync types — `Cache` above has exactly
this problem too, independent of the mixed-receiver issue), and a pointer
receiver used purely out of habit on a small, immutable value type where a
value receiver would avoid an unnecessary allocation/indirection.

## The typed-nil trap

This is one of the most surprising bugs in Go and worth specifically
checking for whenever a function returns an interface (very commonly
`error`) and constructs it from a possibly-nil pointer:

```go
type MyError struct{}
func (e *MyError) Error() string { return "boom" }

func doWork() *MyError {
    return nil // no error occurred
}

func run() error {
    var err *MyError = doWork()
    return err // BUG: returns a non-nil `error` interface wrapping a nil *MyError
}

func caller() {
    if err := run(); err != nil { // true! even though "no error" was intended
        // ...
    }
}
```

The interface value is non-nil because it has a concrete type (`*MyError`)
even though the pointer inside is nil. Flag any function that returns an
interface type where the concrete value comes from a variable typed as a
concrete pointer — the fix is either returning the concrete type directly
where possible, or explicitly returning the literal `nil` interface value
instead of the typed-nil pointer.

## Designing for testability at dependency boundaries

The single most common "this would be easier to test if..." comment in
real Go review: a function or struct depends directly on a concrete
external dependency — a file path, a `*sql.DB`, an `*http.Client`, a
third-party SDK client — instead of a narrow interface at that boundary,
so every test needs the real thing (a tempdir, a live database, a
network call) instead of a fake.

This is the flip side of interface pollution (see
`code-organization-and-api-design.md`), not a contradiction of it — the
point there is not to create interfaces speculatively; the point here is
that a genuine external dependency (I/O, network, database, time,
another service) *is* a real reason to depend on a small interface you
define, sized to only what you call.

```go
// BAD — every caller and every test needs a real file on disk.
func ParseConfig(path string) (*Config, error) {
    data, err := os.ReadFile(path)
    if err != nil { return nil, err }
    return parse(data)
}

// GOOD — works with a real file, an in-memory buffer, an HTTP body,
// stdin, or a test fixture with no filesystem involved.
func ParseConfig(r io.Reader) (*Config, error) {
    data, err := io.ReadAll(r)
    if err != nil { return nil, err }
    return parse(data)
}
```

```go
// BAD — UserService is only ever constructible with a real *sql.DB, so
// every test that exercises it needs a live (or heavily mocked-at-the-
// driver-level) database.
type UserService struct {
    db *sql.DB
}
func (s *UserService) GetUser(ctx context.Context, id string) (*User, error) {
    row := s.db.QueryRowContext(ctx, "SELECT ...", id)
    // ...
}

// GOOD — depends on a narrow interface sized to what it actually calls;
// tests supply a fake, production supplies *sql.DB (which already
// satisfies it), no mocking library or real database required.
type rowQuerier interface {
    QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}
type UserService struct {
    db rowQuerier
}
```

```go
// BAD — direct dependency on the package-level default client makes it
// impossible to substitute a fake in tests, or to add a timeout/retry
// policy without touching every call site.
func FetchUser(id string) (*User, error) {
    resp, err := http.Get(apiBase + "/users/" + id)
    // ...
}

// GOOD — accept an interface (net/http's *http.Client already satisfies
// a `Do(*http.Request) (*http.Response, error)`-shaped one), or accept
// *http.Client itself if that's the narrowest useful boundary here.
type httpDoer interface {
    Do(req *http.Request) (*http.Response, error)
}
func FetchUser(client httpDoer, id string) (*User, error) { ... }
```

Worth a comment whenever a diff introduces a *new* direct dependency on
a file path, a concrete DB/HTTP/SDK client, or another external service
inside a function or struct that has (or is likely to get) unit tests —
not on something clearly fine to depend on concretely (a `main` wiring
function, a one-off script, or a type that specifically needs a concrete
type's extra methods, like `*os.File`'s `Seek`/`Stat`). The fix is
usually a small interface defined where it's consumed (see the
producer-side item in `code-organization-and-api-design.md`), sized to
exactly the methods that call site needs — not the whole concrete type's
surface.

## Time durations

```go
// BAD — reads like "sleep 1000ms" but Duration's underlying unit is
// nanoseconds, so this sleeps for 1000 nanoseconds, not one second.
time.Sleep(1000)
// GOOD
time.Sleep(1000 * time.Millisecond) // or time.Second

// time.After allocates a Timer that isn't garbage-collected until it
// fires. Inside a loop or a repeated select, this leaks a timer per
// iteration if the other case usually wins.
for {
    select {
    case <-ch:
        // ...
    case <-time.After(timeout): // new timer allocated every loop iteration
        // ...
    }
}
// GOOD — reuse a single timer via time.NewTimer + Reset, or restructure
// so time.After is only reached on the path that actually needs to wait.
```

## Resource leaks

The three repeat offenders: HTTP response bodies, `sql.Rows`, and
`os.File`. All three need `Close()` on every path, including error paths.

```go
// BAD — body leaked if ioutil.ReadAll succeeds; also leaked (worse) if
// the caller forgets entirely, which is the more common form of this bug.
resp, err := http.Get(url)
if err != nil { return err }
body, err := io.ReadAll(resp.Body)

// GOOD
resp, err := http.Get(url)
if err != nil { return err }
defer resp.Body.Close()
body, err := io.ReadAll(resp.Body)
```

```go
// BAD — rows never closed if the loop returns early, or even on the
// normal path if Close() is simply never called.
rows, err := db.Query(q)
if err != nil { return err }
for rows.Next() { ... }
// missing: rows.Close() / defer rows.Close()
```

Also watch for **unbounded DB connection pools** — a `database/sql` `DB`
with no `SetMaxOpenConns`/`SetMaxIdleConns`/`SetConnMaxLifetime`
configured is a common production incident waiting to happen under load,
though it's rarely visible in a small diff unless the diff is the one
setting up the `DB` handle.

```go
// BAD — bufio.Writer buffers in memory; Close()ing the underlying file
// without Flush() first silently drops whatever's still in the buffer.
// This isn't a leak like the others above, it's silent data loss.
f, err := os.Create(path)
if err != nil { return err }
defer f.Close()
w := bufio.NewWriter(f)
w.WriteString(data) // never flushed — may never actually reach disk

// GOOD — flush before (or as part of) closing.
w := bufio.NewWriter(f)
w.WriteString(data)
if err := w.Flush(); err != nil { return err }
```

Flag a new `bufio.Writer`/`bufio.NewWriter`-wrapped writer with no
`Flush()` call anywhere on its return paths — the underlying file or
connection getting closed doesn't flush the buffer for you.

## JSON handling

```go
// BAD — unmarshaling into any, then asserting int, panics at runtime:
// encoding/json decodes ALL JSON numbers as float64, never int.
var data map[string]any
json.Unmarshal(body, &data)
count := data["count"].(int) // panics: interface{} is float64, not int

// GOOD — assert the type json/encoding actually produces, or unmarshal
// into a concrete struct instead of any in the first place.
count := int(data["count"].(float64))
```

```go
// BAD — a typo'd struct tag doesn't error; the field just silently never
// gets populated from JSON that has the field spelled correctly.
type User struct {
    Email string `json:"emial"` // typo — Email is always "" after Unmarshal
}
```

Also watch for embedded structs whose JSON field promotion doesn't match
what the author expected — embedding affects JSON marshaling the same way
it affects method promotion, which can silently flatten or duplicate
fields in the encoded output.

## HTTP handlers

```go
// BAD — missing return: after replying with an error, execution falls
// through and the handler keeps running (and may write to the response
// again, which logs a "superfluous response.WriteHeader" warning or
// worse, sends corrupted output).
if err != nil {
    http.Error(w, err.Error(), http.StatusInternalServerError)
}
doMoreWork(w, r) // still executes
```

The default `http.Client`/`http.Server` have no timeouts configured — a
server with no `ReadTimeout`/`WriteTimeout`/`IdleTimeout` is vulnerable to
slow-client resource exhaustion, and a client with no `Timeout` can hang a
goroutine indefinitely on an unresponsive peer. Worth flagging whenever a
diff introduces a new `http.Client{}` or `http.Server{}` literal with no
timeout fields set — not worth flagging on every unrelated line that
merely *uses* an existing, already-configured client.
