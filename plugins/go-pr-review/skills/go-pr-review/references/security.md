# Security

Treat this category with the same seriousness as concurrency — these
mistakes rarely fail a test suite or show up in `go vet`, and the
consequences when they do reach production are often more severe than
anything else on the checklist. Most of these are also unusually cheap to
check: they're pattern-recognizable directly in a diff, without needing
to reason about runtime behavior the way a race condition does.

## SQL and command injection

```go
// BAD — string-built query; a value like `1; DROP TABLE users;--` in id
// executes as SQL, not data.
query := "SELECT * FROM users WHERE id = " + id
rows, err := db.Query(query)

// GOOD — parameterized query; the driver sends id as data, never as SQL.
rows, err := db.Query("SELECT * FROM users WHERE id = ?", id)
```

```go
// BAD — unsanitized input passed to a shell, or interpolated into a
// command string run through a shell.
cmd := exec.Command("sh", "-c", "convert "+userFilename+" out.png")

// GOOD — pass arguments directly to the program, never through a shell;
// exec.Command with separate args doesn't invoke a shell at all, so
// shell metacharacters in userFilename are inert.
cmd := exec.Command("convert", userFilename, "out.png")
```

Flag any `fmt.Sprintf`/string concatenation feeding into `db.Query`,
`db.Exec`, or a similar driver call with a value that isn't a compile-time
constant — parameterized queries (`?`/`$1` placeholders passed as
separate args) are the fix, not more careful escaping. Same logic for
`exec.Command`: flag `"sh", "-c", <built string>` with any
non-constant content; passing arguments as separate `exec.Command` params
instead of through a shell closes the hole entirely, not just narrows it.

## Path traversal

```go
// BAD — id from a request can contain "../../etc/passwd" or an absolute
// path, escaping baseDir entirely.
path := filepath.Join(baseDir, id)
data, err := os.ReadFile(path)

// GOOD — resolve and verify the result is still inside baseDir before
// using it.
path := filepath.Join(baseDir, id)
if rel, err := filepath.Rel(baseDir, path); err != nil || strings.HasPrefix(rel, "..") {
    return fmt.Errorf("invalid path: %s", id)
}
data, err := os.ReadFile(path)
```

`filepath.Join` does *not* sanitize `..` segments out of its result —
flag any `filepath.Join`/`path.Join` call where a segment comes from
request input (a URL path component, a form field, a header) and the
result is used to read, write, or delete a file, unless the diff also
verifies the resolved path stays within the intended directory.

## Weak randomness for security-sensitive values

```go
// BAD — math/rand is deterministic from its seed and not intended to
// resist prediction; using it for anything security-sensitive means an
// attacker who can guess or brute-force the seed can predict every
// value it produces.
token := fmt.Sprintf("%x", rand.Int63()) // math/rand

// GOOD — crypto/rand is designed to be unpredictable.
b := make([]byte, 32)
if _, err := crand.Read(b); err != nil { // crypto/rand
    return "", err
}
token := hex.EncodeToString(b)
```

Flag `math/rand` (including the top-level `rand.Int`/`rand.Intn`/etc.
convenience functions) used to generate anything that needs to resist
guessing: session tokens, password reset tokens, API keys, nonces, CSRF
tokens. `math/rand` is fine for anything that doesn't need that property
(jitter, sampling, test data, load balancing) — don't flag it there.

## Hardcoded secrets

```go
// BAD — a real credential committed to source control, visible to
// anyone with repo access (and to git history forever, even if removed
// later) rather than injected at runtime. (Illustrative shape only —
// don't paste an actual key into a PR comment either.)
const apiKey = "<a live-looking API key literal>"
db, err := sql.Open("postgres", "postgres://admin:hunter2@prod-db/app")
```

Flag a literal that looks like a live credential (API key patterns,
connection strings with an embedded password, private key material) —
the fix is reading it from an environment variable, a secrets manager, or
a config file that's gitignored, not just moving it to a "constants"
file. A placeholder/example value in a test fixture or `.env.example`
isn't this mistake; a value that looks real is.

## TLS misconfiguration

```go
// BAD — disables certificate verification entirely; the client will
// accept a connection to anyone claiming to be the server, defeating
// the point of TLS (trivial to MITM).
transport := &http.Transport{
    TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
}

// GOOD — verify certificates normally; if the goal was trusting a
// private/internal CA, add it to a RootCAs pool instead of disabling
// verification entirely.
transport := &http.Transport{
    TLSClientConfig: &tls.Config{RootCAs: internalCAPool},
}
```

Flag `InsecureSkipVerify: true` on sight — it's almost never the right
fix for a certificate error, even temporarily ("temporary" workarounds
like this are the ones that make it to production). Also worth a mention
when a new `tls.Config` is added with no `MinVersion` set, since the
default floor has historically included versions worth explicitly
excluding depending on the project's compliance requirements.

## Unbounded request body reads

```go
// BAD — no limit on how much the client can send; a large or
// slow-trickling body ties up memory and a goroutine per connection,
// a real denial-of-service vector on a public endpoint.
func handler(w http.ResponseWriter, r *http.Request) {
    body, err := io.ReadAll(r.Body)
    // ...
}

// GOOD — cap it explicitly.
func handler(w http.ResponseWriter, r *http.Request) {
    r.Body = http.MaxBytesReader(w, r.Body, 1<<20) // 1 MiB
    body, err := io.ReadAll(r.Body)
    // ...
}
```

Worth flagging when a diff adds a new HTTP handler that reads `r.Body` in
full (`io.ReadAll`, `json.NewDecoder(r.Body).Decode`, etc.) with no size
limit anywhere in the handler chain (no `http.MaxBytesReader`, no
reverse-proxy-level limit the diff's context makes clear exists) —
skip it for handlers that are internal-only/trusted-caller-only where
this genuinely doesn't matter.

## Leaking internal errors externally

```go
// BAD — the raw error (which may include a SQL query, a file path, a
// stack trace, or internal hostnames) goes straight into the HTTP
// response body, visible to whoever sent the request.
if err != nil {
    http.Error(w, err.Error(), http.StatusInternalServerError)
}

// GOOD — log the real error server-side; return a generic message
// externally.
if err != nil {
    log.Printf("processing request: %v", err)
    http.Error(w, "internal error", http.StatusInternalServerError)
}
```

Flag `err.Error()` (or a `%v`/`%+v` of an internal error) written
directly into an HTTP response, an API payload, or anything else that
crosses a trust boundary to an external caller — internal error detail
belongs in a log, not a response.
