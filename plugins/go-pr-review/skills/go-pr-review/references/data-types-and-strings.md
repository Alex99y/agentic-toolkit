# Data types and strings

## Slices

```go
// Inefficient: repeated re-allocation as the slice grows.
var out []Result
for _, x := range items {
    out = append(out, transform(x))
}
// Better when len(items) is known upfront:
out := make([]Result, 0, len(items))

// Appending to a sub-slice can silently mutate the original's backing
// array if there's spare capacity, corrupting data the original slice's
// owner didn't expect to change.
a := []int{1, 2, 3, 4, 5}
b := a[:2]          // shares a's backing array, cap(b) == 5
b = append(b, 99)   // overwrites a[2] — a is now [1 2 99 4 5]

// A small sub-slice of a huge slice keeps the ENTIRE backing array alive
// as long as the sub-slice is referenced — a real memory leak if the big
// slice was meant to be freed.
huge := loadHugeSlice() // e.g. 1GB
small := huge[:10]      // huge's whole backing array stays alive via small
return small            // caller now unknowingly pins 1GB
// Fix: copy what's needed instead of slicing when lifetime differs.
small := append([]T{}, huge[:10]...)
```

```go
// nil and empty slices behave the same for len()/range/append, but
// differ for JSON (`null` vs `[]`) and `== nil`. Check which check the
// code actually needs:
if s == nil { ... }     // "was it ever allocated"
if len(s) == 0 { ... }  // "is it empty" — usually what's actually meant
```

## Maps

```go
// A size hint avoids rehashing as the map grows, when the size is known
// (or reasonably estimable) upfront.
m := make(map[string]int, len(input))

// A map only grows; deleting entries frees the entries but not the
// underlying bucket memory. A long-lived map with high churn (many
// inserts+deletes over its lifetime) can hold far more memory than its
// current entry count suggests. Worth flagging for a long-lived
// process-global map with unbounded key churn; not worth flagging for a
// short-lived map local to a function call.
```

## Comparisons

```go
// BAD — two interface values are only == if BOTH the dynamic type and
// the value match; comparing an error wrapped by two different concrete
// types is never equal even when their messages look identical.
type errA struct{ msg string }
func (e errA) Error() string { return e.msg }
type errB struct{ msg string }
func (e errB) Error() string { return e.msg }

var e1 error = errA{"not found"}
var e2 error = errB{"not found"}
e1 == e2 // false — different concrete types, even though .Error() matches

// GOOD — structural comparison when that's actually what's meant.
cmp.Diff(e1, e2) // or reflect.DeepEqual, for structural equality in tests
```

`==` on structs compares field-by-field (fine, if all fields are
comparable) but on slices, maps, or functions it doesn't compile at all —
flag a diff that tries to `==` two values of a struct type containing a
slice/map field, since that's a compile error waiting to happen the
moment someone adds such a field. `cmp.Diff` is generally preferred over
`reflect.DeepEqual` in modern code for readable failure output — a
stylistic note in tests, not a correctness one.

## Numeric types

```go
// Octal literal: reads as decimal (755) to anyone not expecting Go's
// C-style octal-via-leading-zero; 0o755 is unambiguous.
os.Chmod(path, 0755)   // → prefer 0o755

// Integer overflow: wraps silently, no panic, no runtime check.
var count uint8 = 255
count++ // count is now 0, not 256 — silent wraparound

// Floating-point equality: almost always a rounding bug waiting to happen.
if price == 19.99 { ... } // prefer math.Abs(price-19.99) < epsilon,
                           // or an integer/decimal type for money
```

Flag unchecked arithmetic specifically when the values are derived from
external/untrusted input (sizes, counts, offsets from a request) — that's
a real risk, not just theoretical, since overflow there can turn into an
out-of-bounds access or an incorrect allocation size.

```go
// BAD — uint subtraction that goes negative wraps to a huge positive
// number instead (uints can't represent negative values). If b is ever
// larger than a, remaining becomes ~18 quintillion, not a small negative
// number you'd notice — commonly turns into an out-of-bounds slice
// access or a loop that never terminates.
func remaining(a, b uint) uint {
    return a - b // no check that a >= b
}

// GOOD — check the ordering, or use a signed type if negative is a
// meaningful, representable result.
func remaining(a, b uint) (uint, error) {
    if b > a {
        return 0, fmt.Errorf("b (%d) exceeds a (%d)", b, a)
    }
    return a - b, nil
}
```

This is probably the single most common `uint`-related bug in real Go
code: `len(a) - len(b)`, "remaining capacity" calculations, or any
subtraction between two `uint`/`uint32`/`uint64` values where the diff
doesn't first establish the minuend is at least as large as the
subtrahend. Flag any new `uint`-family subtraction where that ordering
isn't obviously guaranteed by the surrounding code.

## Strings

```go
// Byte-indexing a string with non-ASCII content slices into the middle
// of a multi-byte UTF-8 sequence, producing garbage.
s := "héllo"
s[1] // NOT 'é' — it's one byte of its multi-byte UTF-8 encoding

// correct rune-aware iteration:
for i, r := range s { ... } // i is a byte offset, r is a decoded rune

// string += in a loop reallocates and copies on every iteration.
var s string
for _, w := range words {
    s += w // O(n^2) total work
}
// Better:
var b strings.Builder
for _, w := range words {
    b.WriteString(w)
}
s := b.String()
```

- `strings.Trim`/`TrimLeft`/`TrimRight` take a **cutset** (a set of
  characters to strip from either end), not a prefix/suffix string — a
  very common confusion with `strings.TrimPrefix`/`TrimSuffix`, which do
  take a literal string. `strings.Trim(s, "hello")` strips any of the
  characters `h`,`e`,`l`,`o` from both ends of `s`, which is rarely what
  someone reaching for it meant.
- Useless conversions: repeated `[]byte(s)` / `string(b)` round-trips in a
  hot path each allocate and copy — flag when it's in a loop or a clearly
  hot path, not for a one-off conversion that's fine as-is.
