# Code organization and API design

These are less about crashes and more about a codebase getting harder to
change over time — but they're still worth real comments, because API
shape mistakes (a bad interface, a leaky constructor) are far more
expensive to fix after other code depends on them than a local bug is.
Weight these lower than a concurrency bug or a resource leak, but don't
skip them just because nothing will panic.

(Unintended variable shadowing, also originally grouped with this
category, has its own worked example in errors-and-control-flow.md,
since it shows up most often via a shadowed `err`.)

## Unnecessary nested code

```go
// Harder to follow — the "happy path" is buried inside two levels of if.
func process(item *Item) error {
    if item != nil {
        if item.Valid() {
            return save(item)
        } else {
            return errors.New("invalid item")
        }
    }
    return errors.New("nil item")
}

// GOOD — guard clauses (early returns) flatten it; the happy path reads
// straight down.
func process(item *Item) error {
    if item == nil {
        return errors.New("nil item")
    }
    if !item.Valid() {
        return errors.New("invalid item")
    }
    return save(item)
}
```

Flag when a diff adds a new `if`/`else` nested more than ~2 levels deep
where inverting the condition and returning early would flatten it —
especially in a function that's growing, since nesting compounds fast.

## Misusing `init` functions

`init` runs automatically before `main` (or before tests), with no way
for the caller to control *when*, pass it arguments, or observe an error
it returns — it can only `panic`. Flag an `init` that does anything
riskier than trivial, deterministic setup (registering a codec, setting a
package-level constant): opening a network connection, reading a file
that might not exist, or anything whose failure should be a caller-visible
error rather than a process crash at import time. It also makes testing
harder — every test in the package pays `init`'s cost/side effects
whether or not that test touches the thing `init` set up.

## Overusing getters and setters

```go
// Unnecessary — this is just field access with extra steps, common in
// languages that require it (Java) but not idiomatic Go.
type Config struct {
    timeout time.Duration
}
func (c *Config) GetTimeout() time.Duration { return c.timeout }
func (c *Config) SetTimeout(d time.Duration) { c.timeout = d }

// GOOD — a plain exported field, unless there's a real reason (validation
// on set, computed on get, guarding with a mutex) to intercept access.
type Config struct {
    Timeout time.Duration
}
```

Only flag this when the getter/setter is doing nothing but forwarding —
if `SetX` validates input or `GetX` computes/locks, it's earning its
keep and isn't this mistake.

## Interface pollution

```go
// BAD — an interface defined for a single concrete implementation, with
// no second implementation in sight and no test-double reason for it.
type UserStore interface {
    Get(id string) (*User, error)
    Save(u *User) error
}
type postgresUserStore struct{ db *sql.DB }
// ... only one implementation exists anywhere in the codebase
```

An interface earns its place when there are genuinely ≥2 implementations,
or a real need to decouple a package from a concrete dependency it
shouldn't import directly (e.g. for testing). An interface with exactly
one real implementation and no test-double need is usually just
indirection — flag it as premature abstraction, not because interfaces
are bad, but because this one isn't paying for itself yet.

That "for testing" carve-out is the common case in practice, not an edge
case — see `functions-methods-stdlib.md`'s "Designing for testability at
dependency boundaries" for what a genuine one looks like (a DB/HTTP/SDK
client, a filesystem dependency) versus this item's bad example (an
interface with no real second implementation and nothing external to
substitute in tests).

## Interface on the producer side

```go
// BAD — the producer package defines and exports the interface alongside
// its own concrete implementation.
package store
type UserStore interface { Get(id string) (*User, error) }
type PostgresUserStore struct{ /* ... */ }
func (p *PostgresUserStore) Get(id string) (*User, error) { /* ... */ }
```

An interface should usually live in the package that *consumes* it (so
that package can define exactly the narrow surface it needs), not the
package that implements it. When the implementing package also exports
the interface, every consumer is coupled to that interface's shape even
if they only need one method of it — flag this pattern when a diff adds a
new interface in the same package as its sole implementation.

## Returning interfaces from functions

```go
// BAD — forces every caller to work through the interface, even ones
// that would benefit from the concrete type's extra methods.
func NewCache() Cache { return &memoryCache{...} }

// GOOD — return the concrete type; let the caller narrow to an interface
// at the point where they actually need to (e.g. as a function parameter
// they define).
func NewCache() *MemoryCache { return &memoryCache{...} }
```

"Accept interfaces, return structs" is the shorthand — flag a constructor
or factory function whose return type is an interface when there's no
clear reason the caller needs that abstraction at the construction site.

## `any` says nothing

```go
// BAD — the compiler can't help catch a wrong-type call site, and every
// reader has to infer the intended type from context or a type switch.
func Process(data any) any { ... }

// GOOD — a concrete type, or a generic type parameter when the function
// genuinely needs to work across multiple types with the same logic.
func Process(data []Record) []Result { ... }
func Process[T Numeric](data []T) []T { ... }
```

Flag `interface{}`/`any` in a new function signature (parameters or
return) where a concrete type or a generic type parameter would work just
as well — it's not always wrong (a truly generic container, or
interop with something like `encoding/json` that requires it), but it
should be a deliberate choice, not a default reached for to avoid picking
a real type.

## Confusion about when to use generics

Generics are for algorithms/data structures that behave identically
across multiple concrete types (a generic `Map`/`Filter`, a type-safe
container). They're not a substitute for a single `interface{}` parameter,
and they're not needed at all if the function only ever operates on one
type in practice. Flag a new generic function/type with only one call
site or only one type argument used anywhere in the diff — that's a sign
the generic parameter isn't earning its complexity yet.

## Type embedding pitfalls

```go
// Embedding promotes Logger's methods onto Service directly, which means
// Service now silently satisfies any interface Logger does, and every
// Logger method is part of Service's exported API whether intended or not.
type Service struct {
    *log.Logger // promotes Log, Println, etc. onto Service
    db *sql.DB
}
```

Embedding is for genuine "is-a"/behavior-reuse relationships, not just a
shortcut to avoid writing forwarding methods. Flag a new embedded field
when: it promotes methods that become part of the outer type's public API
without the author clearly intending that (check whether those methods
make sense being called on the outer type), or when it causes the outer
type to unintentionally satisfy an interface it wasn't meant to.

## Not using the functional options pattern

```go
// BAD — every new optional parameter breaks all call sites, or forces an
// awkward zero-value ("just pass 0 if you don't care") convention.
func NewServer(addr string, timeout time.Duration, maxConns int, tls bool) *Server

// GOOD — new options can be added without touching existing call sites.
func NewServer(addr string, opts ...Option) *Server
type Option func(*Server)
func WithTimeout(d time.Duration) Option {
    return func(s *Server) { s.timeout = d }
}
```

Flag a constructor gaining its 4th+ parameter (especially bools or
same-typed values where call-site order is easy to get wrong) as a
candidate for functional options instead — but don't force this on a
constructor with 2-3 genuinely required parameters that aren't likely to
grow.

## Project misorganization

Package structure should reflect domain boundaries (what the code *does*)
rather than technical layers repeated inside every feature
(`handlers/`, `models/`, `services/` each containing one file per
feature) or a flat dump of everything at the module root. This is hard to
assess from a single PR's diff in isolation — flag it when a diff adds a
new file to a package whose existing contents clearly don't relate to it
(a payments-related file landing in a package otherwise about user
auth), which is visible even from a small diff.

## Creating "utility"/"common"/"helpers" packages

```go
// BAD — a package named for what kind of code it holds, not what the
// code does. Tends to accumulate unrelated functions with nothing in
// common except "didn't fit elsewhere."
package utils
func FormatDate(t time.Time) string { ... }
func RetryWithBackoff(fn func() error) error { ... }
func ParseConfig(path string) (*Config, error) { ... }
```

Flag a new file added to a package named `utils`/`common`/`helpers`/
`shared` — the fix is usually to name the package (and put the function
in it) after what the function actually does: `dateformat`, `retry`,
`config`.

## Ignoring package name collisions

```go
// BAD — a local package or variable named the same as a common stdlib
// package forces every subsequent use of the real package in this file
// into an awkward alias.
import "time"
func time() string { ... } // shadows the "time" package name in this file
```

Flag a new package, function, or frequently-used local variable named the
same as a common stdlib package (`time`, `http`, `sort`, `context`) —
it's legal but forces ugly import aliasing anywhere both are needed
together, and it's confusing to read regardless.

## Missing code documentation

```go
// BAD — no doc comment on an exported identifier; godoc and IDE
// tooltips show nothing useful.
func Retry(fn func() error, attempts int) error { ... }

// GOOD — starts with the identifier's name, per Go convention.
// Retry calls fn up to attempts times, returning the last error if all
// attempts fail.
func Retry(fn func() error, attempts int) error { ... }
```

Flag a new exported (capitalized) function, type, or package-level
variable/constant added with no doc comment — this is genuinely
low-severity compared to everything else in this file, so don't let it
crowd out real bugs in a review; a couple of missing doc comments belong
in the style section or a brief closing mention, not top billing.
