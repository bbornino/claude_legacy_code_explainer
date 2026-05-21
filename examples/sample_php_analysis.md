# Analysis: sample_php.php

## What It Does

This script is a single-file employee portal dispatching on a `$_REQUEST['action']` parameter. It connects to MySQL as `sa` with a hardcoded password, opens a session, and routes to one of nine handlers: login, employee search, employee update, document upload, report inclusion, admin shell, password reset, and employee deletion.

Observable effects:
- Reads/writes the `employees` table in `hr_portal`, including SSN, salary, `is_admin`, and `pass_hash` columns
- Writes uploaded files into `/var/www/hr/docs/` under attacker-controlled names
- Includes arbitrary PHP files from `/var/www/hr/reports/` based on `$_GET['type']`
- Executes shell commands via `shell_exec()` and `system()`
- Emits HTML directly with no escaping; emits full SQL and `mysql_error()` to the browser on failure

Hidden control flow:
- `register_globals = On` means `$uid`, `$admin`, `$dept` are populated from `$_GET`, `$_POST`, or `$_SESSION` automatically — attacker can set any of these via URL parameters
- `check_logged_in()` calls `header("Location: ...")` without `exit()`, so execution continues past the redirect
- `error_reporting(E_ALL)` + `display_errors=1` leaks file paths, SQL, and DB error text to any client
- The handlers are not `elseif` — multiple actions can fire in one request if `$action` matches several conditions through later mutation (it doesn't here, but the structure invites it)

## Risk Flags

- **[Critical] `shell_exec($_REQUEST['cmd'])` in `admin_exec`** — unrestricted RCE. `check_admin()` gates it via `$admin != 1`, but `$admin` comes from `register_globals`, so `?action=admin_exec&admin=1&cmd=id` executes as the web user.
- **[Critical] `system("rm -rf $dir")` in `delete`** — shell command injection via `$_GET['username']`. `username=;rm -rf /` runs as the web user. No escaping, no `escapeshellarg()`.
- **[Critical] `include("/var/www/hr/reports/" . $_GET['type'] . ".php")`** — local file inclusion. With PHP <5.3 the null-byte trick (`type=../../../../etc/passwd%00`) reads arbitrary files; with `allow_url_include=On`, this is RFI to a remote PHP payload.
- **[Critical] `move_uploaded_file($tmp, "/var/www/hr/docs/" . $_FILES['document']['name'])`** — no extension whitelist, no MIME check, no path sanitization. Uploading `shell.php` and requesting `/hr/docs/shell.php` yields RCE since the directory is served by Apache as PHP. `name=../../../etc/cron.d/x` escapes the upload directory.
- **[Critical] `register_globals` reliance in `check_logged_in()` and `check_admin()`** — entire authentication model is bypassable. `?uid=1&admin=1` satisfies both checks without any login.
- **[Critical] SQL injection in `login`** — `$_POST['username']` and `md5($_POST['password'])` interpolated into the query. Classic `' OR '1'='1` bypasses authentication and returns the first row (typically the admin).
- **[High] SQL injection in `search`, `update_employee`, `set_password`, `delete`** — every `mysql_query()` interpolates `$_GET`/`$_POST`/`$_SESSION` directly. `update_employee` is exploitable for full table modification and `delete` for full table deletion via `UNION`/stacked-query variants.
- **[High] `update_employee` has no auth check at all** — comment claims "only HR can reach this page via the navigation menu." Any unauthenticated POST can modify any employee row, including `is_admin`.
- **[High] `set_password` accepts `$_POST['newpass']` with no current-password check** — combined with no CSRF token, a forged POST from any site silently rewrites the victim's password. Session fixation is also viable since `session_regenerate_id()` is commented out.
- **[High] No CSRF tokens anywhere** — `update_employee`, `set_password`, `delete`, `upload_doc`, `admin_exec` all act on cookie-authenticated sessions with no anti-CSRF defense.
- **[High] `md5($pass)` for password storage** — unsalted MD5 is broken; rainbow tables resolve common passwords in seconds.
- **[High] `mysql_connect(..., "sa", "C0rp\$ql2001!")`** — hardcoded credentials in source; database user appears to be the SQL Server-style `sa` administrator account, so any SQL injection yields full DB compromise.
- **[High] `echo "Query: $sql"` and `die("DB error: " . mysql_error() . " — Query: $sql")`** — leaks schema and injected payload state to attackers; `display_errors=1` compounds this.
- **[High] XSS throughout** — `lastname`, `firstname`, `ssn`, `dept_code`, and `$filename` echoed without `htmlspecialchars()`. Stored XSS via any DB field; reflected XSS via uploaded filename in the success link.
- **[Medium] `check_logged_in()` missing `exit()` after `header("Location: ...")`** — the redirect header is sent but PHP continues executing the handler. Search/upload/report logic runs and returns its output in the redirect response body. An attacker with a non-following client sees the full response.
- **[Medium] `if (!$uid)`** — type juggling: `$uid = "0abc"` is truthy, `$uid = "0"` is falsy. Loose check is unreliable; should be a strict session presence test.
- **[Medium] `$_SESSION['admin'] == 1`** in `delete` — only handler that uses session state instead of the global; inconsistent with `check_admin()`, so changing one does not fix the other.
- **[Medium] SSN and salary returned to every authenticated user** in `search` — no role check, no column-level authorization, no audit log.
- **[Low] `session_regenerate_id()` commented out** — session fixation: an attacker who plants a session ID before login retains the same ID post-authentication.
- **[Low] `error_reporting(E_ALL | E_NOTICE)` + `display_errors=1`** — leaks absolute filesystem paths and internal variable names on every notice.

## Modernization Path

- **Disable `register_globals` in `php.ini`** immediately (`register_globals = Off`). It was removed in PHP 5.4; the fact that this code depends on it is itself a deployment risk. Replace every `global $uid, $admin` with explicit `$_SESSION['uid']`, `$_SESSION['admin']` reads and validate they were set by the login handler, not by request input.
- **Replace `mysql_*` with PDO and prepared statements throughout.** Every query becomes:
  ```php
  $stmt = $pdo->prepare("SELECT ... WHERE username = :u AND pass_hash = :h AND active = 1");
  $stmt->execute([':u' => $user, ':h' => $hash]);
  ```
  The `mysql_*` extension was removed in PHP 7.0; this is non-negotiable for any host upgrade.
- **Replace `md5($pass)` with `password_hash($pass, PASSWORD_ARGON2ID)`** at registration and `password_verify($pass, $row['pass_hash'])` at login. Migrate existing hashes lazily: on successful MD5 login, rehash and store with `password_hash()`.
- **Eliminate `shell_exec($_REQUEST['cmd'])` entirely** — the admin shell handler has no legitimate web-tier use case. Delete the handler. If administrative tasks are required, expose them as named operations (`action=rebuild_index`) that map to fixed internal functions with no user-supplied command string.
- **Replace `system("rm -rf $dir")` with PHP filesystem APIs**: validate `$username` against `/^[a-z0-9_]+$/`, then use a recursive `RecursiveDirectoryIterator` / `unlink()` loop, or at minimum `escapeshellarg($dir)` with a `realpath()` check confirming the resolved path is inside `/var/www/hr/docs/`.
- **Replace dynamic `include` with a whitelist dispatch**:
  ```php
  $allowed = ['headcount' => 'headcount.php', 'salary' => 'salary.php'];
  if (!isset($allowed[$_GET['type']])) { http_response_code(400); exit; }
  include "/var/www/hr/reports/" . $allowed[$_GET['type']];
  ```
  Never construct the include path from user input.
- **Harden `upload_doc`**: generate a server-side filename (`bin2hex(random_bytes(16))`), enforce an extension whitelist against the original name (`pdf`, `docx`, `xlsx` only), verify MIME via `finfo_file()`, store outside the document root, and serve via a download script that sets `Content-Disposition: attachment`. Configure Apache to refuse PHP execution under `/var/www/hr/docs/` (`php_admin_flag engine off`).
- **Add a code-level auth check to `update_employee`** that verifies `$_SESSION['admin'] === 1` (strict comparison, not `== 1`). Remove `is_admin` from the field list accepted from `$_POST`; admin promotion belongs in a separate, audited handler.
- **Add CSRF tokens to every state-changing handler**: generate `$_SESSION['csrf'] = bin2hex(random_bytes(32))` at login, embed in every form as a hidden field, and require `hash_equals($_SESSION['csrf'], $_POST['csrf'])` before any `UPDATE`/`DELETE`/upload/password-change action.
- **Require current password in `set_password`**: re-authenticate with `password_verify($_POST['current'], $row['pass_hash'])` before applying the new password. Enforce a complexity policy.
- **Uncomment `session_regenerate_id(true)` immediately after successful login** to prevent session fixation. Set session cookies with `HttpOnly`, `Secure`, and `SameSite=Strict`.
- **Add `exit;` after every `header("Location: ...")`** to prevent post-redirect handler execution.
- **Escape all output with `htmlspecialchars($value, ENT_QUOTES, 'UTF-8')`** at every `echo` of DB or user data. Long term, migrate templates to Twig with autoescaping enabled (Rewrite scope for the template layer).
- **Set `display_errors = Off` and `log_errors = On`** in production `php.ini`. Remove all `die(... mysql_error() ...)` patterns; log to a file and return a generic error page.
- **Move DB credentials out of source** into a file outside the document root (`/etc/hr_portal/db.ini`) read via `parse_ini_file()`, owned by root and readable only by the web user. Rotate the password and provision a least-privilege account (`SELECT`, `INSERT`, `UPDATE` on `employees` only; no `DROP`, no admin role).
- **Restrict SSN and salary access**: add a `role` check in the `search` handler; return SSN only to users with an HR role, and log every access of these columns to an audit table.
- **(Rewrite scope)** The dispatcher pattern (`if ($action == ...)`) with nine inline handlers, mixed I/O, business logic, and presentation, should be replaced with a routing framework (Slim or Laravel) and split into controllers, a data-access layer using PDO, and templates. This is a 2–4 week effort for a single developer and should be planned alongside the PHP 8 upgrade that the `mysql_*` removal forces.
