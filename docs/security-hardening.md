# Security hardening (2026-10-21)

These changes are local source changes. They do not change an existing database,
remove existing users/files, deploy containers, or modify the reverse proxy.

- `/center-logo/<center_id>/<filename>` serves only the logo filename recorded for
  that center. Corporate documents remain behind the administrator-only route.
- Ticket media uses the same owner, assigned technician and center authorization
  as ticket details. Managers and technician leads cannot read another center's media.
- Customer pickers use DOM text nodes, including device options. Dashboard/report
  HTML templates escape customer and device text before insertion.
- Uploaded images require a matching extension, MIME type and file signature.
  Accepted image types are PNG, JPEG, GIF, WebP and BMP; SVG is rejected. PDF and
  supported video containers have signature/extension checks too. This is not full
  file decoding or malware scanning. All upload responses use `nosniff` and a sandbox
  policy. Non-image/video uploads, including PDFs and legacy HTML/SVG, download as
  attachments. Existing files are not rewritten or deleted.
- POST bodies over 128 MiB are rejected before reading the body or opening a DB
  connection. This allows a 100 MiB ShareSpace attachment plus form overhead.
  Multiple large files in one submission may need to be split into separate uploads.
  Configure the reverse proxy to enforce an appropriate request size, connection
  count and read timeout too; this application limit is not a complete DoS defense.
- `TRUSTED_PROXY_CIDRS` defaults to empty, so `X-Forwarded-For` is ignored. Configure
  only the actual immediate proxy addresses/networks. The client chain is evaluated
  from right to left, stopping at the first untrusted hop. Do not trust all addresses
  or an entire shared network. Ensure the proxy appends the real peer address or
  overwrites the forwarded header. Without this setting, users behind one proxy
  share its IP for the existing per-username login limiter.
- `SEED_DEMO_DATA` defaults to disabled; only an explicit `1` enables demo accounts.
  For an empty database, set `INITIAL_ADMIN_USERNAME` and `INITIAL_ADMIN_PASSWORD`
  privately to create the first administrator. Existing demo accounts are unaffected
  and must be reviewed separately before production use. `.env.example` contains
  empty placeholders, not live credentials.

## Verification

Run from the project root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Tests use fictional data and temporary directories/SQLite fixtures. The security
suite covers logo/document separation, authorization across roles/centers, fake
uploads, safe download headers, request size rejection before reading, CSRF and
multipart parsing order, proxy trust, login throttling and demo defaults. Node.js
is used for DOM behavior tests of customer pickers (skipped if Node is absent).
The older API end-to-end tests now use a fixed clock to match their fixed dates.

PostgreSQL-specific behavior, a real browser, actual proxy configuration, existing
stored files/accounts, installed production dependencies and online deployment
have not been validated by these local tests.
