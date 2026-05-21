# Analysis: sample_c.c

## What It Does

`dispatch.c` is a single-threaded TCP daemon listening on a port supplied as `argv[2]`. On startup it:

1. Copies `argv[1]` into a 128-byte stack buffer and opens it as a config file.
2. From that config, executes `chmod`/`chown` shell commands built from the `handler_dir` value, and runs the `log_cmd` value directly through `system()`.
3. Prompts on stdin for a worker count, allocates `n_workers * sizeof(Record)` bytes without bounds or success checks.
4. Accepts TCP connections in a loop. For each connection it calls `parse_frame()`, which:
   - Reads up to 1024 bytes into a 256-byte stack buffer.
   - Prints the received bytes through `printf()` with no format specifier.
   - Reads a line from stdin into a 64-byte buffer via `gets()` — note this reads from the *daemon's* stdin, not the socket, so under inetd or piped input this is also remote-influenced.
   - Builds `[client_ip] <data>` in a 256-byte buffer with `sprintf`.
   - Extracts a record type with `sscanf("%s …")`, no width.
   - Appends the record to a 64-slot ring buffer using `strcpy` on three attacker-controlled fields.
   - Builds `<HANDLER_DIR>/<rtype>.sh '<record>' >> /var/log/dispatch.log 2>&1` and runs it through `system()`.
   - Passes the assembled log line back through `fprintf(g_log, fmt)` as a format string.

Hidden state: `g_ring`, `g_head`, `g_count`, `g_log` are file-scope globals. `g_count` increments without bound; `g_head` wraps via modulo but `g_count` does not, so any code reading `g_count` as a slot index is wrong after 64 records. The work buffer is unreachable-freed; the process leaks it for its lifetime. The chroot referenced in the header comment is not present in the code.

## Risk Flags

- **[Critical]** `system(val)` in `reload_config()` executes any string under the `log_cmd` key in the config file. Anyone who can write the config (including via the `handler_dir` chmod/chown logic itself, which runs on attacker-supplied paths) gets arbitrary code execution as the daemon user.
- **[Critical]** `sprintf(cmd, "%s '%s' >> %s 2>&1", handler, record, LOG_PATH); system(cmd);` in `dispatch_record()`. `record` is raw TCP payload. A single quote followed by `;`, backtick, or `$()` breaks out of the quoting and runs arbitrary shell commands. Remote, unauthenticated RCE.
- **[Critical]** `sprintf(handler, "%s/%s.sh", HANDLER_DIR, rtype)` with no whitelist. `rtype` comes from `sscanf` on network data; `../../../tmp/x` or absolute-path injection via `rtype` containing `/` traverses out of `HANDLER_DIR`. Combined with the `system()` call above, attacker chooses which binary to execute.
- **[Critical]** `n = recv(fd, raw, 1024, 0)` writes up to 1024 bytes into a 256-byte stack buffer `raw[]`. Classic stack buffer overflow on every connection, controlled by the remote client. Return address overwrite.
- **[Critical]** `printf(raw)` and `log_msg(combined)` → `fprintf(g_log, fmt)`. Both pass attacker-controlled bytes as the format string. `%n` writes attacker-chosen values to attacker-chosen addresses; `%s`/`%x` leak stack memory including any secrets or pointers useful for bypassing ASLR before the overflow above.
- **[Critical]** `gets(host_buf)` reads unbounded input into a 64-byte buffer. Removed from C11 because it is unconditionally exploitable. Even if stdin is normally a terminal, under inetd/xinetd or any wrapper that pipes data, this is remotely reachable.
- **[High]** `strcpy(g_ring[slot].src_host, host)`, `strcpy(..., rec)`, `strcpy(..., rtype)` in `enqueue()`. All three source strings can exceed their destination sizes (64/256/16); `rtype` is the worst because `sscanf("%s")` placed up to 256 bytes into a 64-byte stack array before `strcpy` then copies into a 16-byte struct field.
- **[High]** `sprintf(combined, "[%s] %s", client_ip, raw)` into a 256-byte buffer with a 256-byte `raw` plus prefix. Overflows by at least the prefix length on full-length input.
- **[High]** `strcpy(config_path, argv[1])` into a 128-byte buffer with no length check. Local privilege boundary if the daemon is launched by a less-privileged supervisor passing user-influenced arguments.
- **[High]** `void *work_buf = malloc(n_workers * sizeof(Record));` — `n_workers` is an unchecked `unsigned int` read by `scanf("%u")`. `n_workers * sizeof(Record)` overflows `size_t` on values near `SIZE_MAX / sizeof(Record)`, yielding a tiny allocation that subsequent code (if it ever wrote to `work_buf`) would overrun. The return value is not checked.
- **[High]** TOCTOU in `dispatch_record()`: `stat(handler, &st)` then `system("<handler> …")` — the path can be swapped to a symlink between the check and the shell invocation. Same pattern in `reload_config()` between `stat(path)` and `fopen(path)`.
- **[High]** `fp = fopen(path, "r"); while (fscanf(fp, …))` — `fopen` return value not checked. On failure `fp` is NULL and `fscanf` dereferences it, crashing the daemon (DoS) or, depending on libc, doing something worse.
- **[Medium]** `raw[n] = '\0'` after `recv(fd, raw, 1024, 0)`. Even when `recv` honors a smaller size, the comment writes past `raw[]` if `n == sizeof(raw)`. Off-by-one independent of the overflow above.
- **[Medium]** `enqueue()` never checks `g_count < MAX_CONN` before writing. `g_head % MAX_CONN` masks the overflow but `g_count` grows without bound; any consumer that uses `g_count` as a slot count reads past the end of `g_ring`.
- **[Medium]** `sscanf(raw, "%s %d", rtype, &priority)` with no field width. 64-byte `rtype` overflowed by any single token longer than 63 bytes.
- **[Medium]** `port = atoi(argv[2])` — no range check. Negative or out-of-range values are silently cast to `uint16_t` via `htons`, binding an unintended port.
- **[Medium]** `socket()`, `bind()`, `listen()`, `accept()` return values unchecked. Bind failure means the daemon proceeds to `accept(-1, …)` in a tight loop, hot-spinning CPU.
- **[Medium]** Memory leak of `work_buf` is dwarfed by the leak comment in the header — the bigger leak is implied per-connection state never explicitly cited; regardless, `free(work_buf)` is unreachable because the `while(1)` loop has no exit.
- **[Low]** `inet_ntoa()` returns a pointer to a static buffer overwritten on each call. In this single-threaded loop it works, but any future threading silently corrupts client IPs across handlers.
- **[Low]** `g_log` opened with no `setvbuf`; `fflush` after every write is the only thing keeping log lines on disk. Removing the flush silently loses logs on crash.

## Modernization Path

- **`log_msg(fmt)` → `fprintf(g_log, "%s", fmt)`** and rename the parameter to `msg`. Never pass external data as a format string. Apply the same fix to `printf(raw)` → `printf("%s", raw)`.
- **`recv(fd, raw, 1024, 0)` → `recv(fd, raw, sizeof(raw) - 1, 0)`**. Match the length argument to the buffer. Then validate `n` as `ssize_t`, reject `n <= 0`, and only then write `raw[n] = '\0'`.
- **`gets(host_buf)` → delete entirely.** If this read is genuinely needed, replace with `fgets(host_buf, sizeof(host_buf), stdin)` and strip the trailing newline. More likely this line is dead code that should be removed.
- **`strcpy` in `enqueue()` → `snprintf(g_ring[slot].src_host, sizeof(g_ring[slot].src_host), "%s", host)`** for each field. Treat truncation as expected, not an error.
- **`sprintf(combined, …)` → `snprintf(combined, sizeof(combined), "[%s] %s", client_ip, raw)`** and check the return value against `sizeof(combined)` to detect truncation.
- **`sprintf(handler, …)` and `system(cmd)` in `dispatch_record()` → eliminate the shell entirely.** Maintain an explicit whitelist of valid `rtype` values mapped to absolute handler paths. Validate `rtype` matches `[A-Za-z0-9_]{1,15}` before lookup. Invoke the handler with `fork()` + `execve(handler_path, argv, envp)` passing `record` as an argument, never as part of a shell string. (Rewrite scope for the dispatch model.)
- **`reload_config()` `system(val)` and `system(cmd)` → remove both.** Config files must not contain executable commands. Move log rotation to `logrotate(8)` with a dedicated config; remove `log_cmd` entirely. For `handler_dir`, store the path only and apply permissions in an out-of-band install step, not from the running daemon.
- **`fopen` without check → `fp = fopen(path, "r"); if (!fp) { /* log errno, return -1 */ }`**. Same for the `g_log` open in `main()`; if logging is mandatory, refuse to start.
- **`stat()` + `system()` / `stat()` + `fopen()` TOCTOU → drop the `stat`.** Open the file with `open(path, O_RDONLY | O_NOFOLLOW)` and `fstat(fd, &st)` against the open descriptor. For handlers, use `fexecve()` against an `open(O_PATH)` descriptor where available.
- **`sscanf(raw, "%s %d", rtype, &priority)` → `sscanf(raw, "%63s %d", rtype, &priority)`** and check the return value equals 2. Better: replace ad-hoc parsing with an explicit length-prefixed framing scheme since input now arrives from the post-2004 bridge with no validation.
- **`strcpy(config_path, argv[1])` → `snprintf(config_path, sizeof(config_path), "%s", argv[1])`** and detect truncation; reject and exit if the path didn't fit.
- **`port = atoi(argv[2])` → `strtol(argv[2], &end, 10)`** with explicit range check `1 <= port <= 65535` and `*end == '\0'`.
- **`malloc(n_workers * sizeof(Record))` → `calloc(n_workers, sizeof(Record))`** to get overflow detection, and check the result. Bound `n_workers` to `MAX_CONN` *before* the allocation, not after.
- **`enqueue()` ring discipline → add `if (g_count >= MAX_CONN) { /* drop oldest or reject */ }`** and stop incrementing `g_count` once full. Use `g_head` and `g_tail` as the canonical indices; derive count as `(g_head - g_tail) % MAX_CONN`.
- **Unchecked `socket`/`bind`/`listen`/`accept` → check each return value**, log via `strerror(errno)`, and exit with non-zero on bind failure. Wrap `accept()` to `continue` on `EINTR` and exit on persistent errors.
- **`inet_ntoa()` → `inet_ntop(AF_INET, &cli_addr.sin_addr, ipstr, sizeof(ipstr))`** with a local `char ipstr[INET_ADDRSTRLEN]`. Thread-safe and IPv6-ready when you switch to `getnameinfo()`.
- **Process model → (Rewrite scope).** The combined problems — shell dispatch, format-string logging, ring buffer mismatch, single-threaded `accept` loop with no timeouts, no auth, no TLS, listening on a routable port despite the "internal" comment — indicate this daemon should be replaced. If the protocol must be preserved, rewrite as a forking or thread-pooled service in C with the fixes above, or port to Go/Rust where the dispatch-to-handler step uses `os/exec.Command` / `std::process::Command` with argument lists (never shell strings). The migration boundary is the TCP frame format; keep that stable and replace everything behind it.
- **Header comment claims → remove.** Delete the "runs inside a chroot jail" and "all inputs validated by the mainframe" comments. They are actively misleading future maintainers. Replace with current operational reality.
