# Taskmaster — Comprehensive Evaluation & Testing Guide

This guide provides a step-by-step protocol for evaluating and testing the entire **Taskmaster** pipeline. It can be executed manually by an evaluator or automated by an AI testing agent.

---

## 1. Automated Test Suite (Unit & Integration)

Run the full `unittest` test suite before manual evaluation:

```bash
python3 -m unittest discover -s tests -v
```

**Expected Outcome:**
- All tests pass with `OK` (0 failures, 0 errors).
- Covers config validation, FSM state transitions, process manager, socket IPC server/client, and CLI parser.

---

## 2. Launching the Daemon

### 2.1 Silent Background Mode (Default)
Starts `taskmasterd` in the background without polluting the terminal:

```bash
./taskmasterd &
sleep 2
```

**Verify Daemon Startup:**
```bash
# Check socket exists with correct permissions (0600)
ls -l /tmp/taskmaster.sock

# Check process is alive
pgrep -fl taskmasterd
```

### 2.2 Foreground Mode (Alternative)
For live colored terminal output:
```bash
./taskmasterd -f
```

---

## 3. Interactive Shell & Pipeline Testing (`taskmasterctl`)

### 3.1 Initial Status
Check that all programs configured in `config.toml` were loaded and initialized:

```bash
printf "status\nquit\n" | ./taskmasterctl
```

**What to Check:**
- Active programs (`test_sleep_*`, `heartbeat`, `test_env`, `test_umask`, `test_workers_*`) are in `RUNNING`.
- Non-autostarted programs (`test_dep_db`, `test_dep_web`, `test_always`, `test_never`) are in `STOPPED (not started)`.
- Rapidly failing programs (`test_false`, `test_true`, `test_nonexist`) are in `FATAL (startup failed)`.

---

### 3.2 Process Lifecycle Management (`start`, `stop`, `restart`)

Test individual and group actions:

```bash
# Stop all 3 instances of test_workers
printf "stop test_workers\nquit\n" | ./taskmasterctl

# Verify STOPPED state with reason "by request"
printf "status test_workers\nquit\n" | ./taskmasterctl

# Start test_workers again
printf "start test_workers\nquit\n" | ./taskmasterctl

# Restart a single instance
printf "restart test_workers_0\nquit\n" | ./taskmasterctl
```

---

### 3.3 Dependency Ordering Verification (`depends_on`)

`test_dep_web` depends on `test_dep_db`. Verify strict gating:

```bash
# 1. Attempt starting dependent service before dependency is running -> MUST FAIL
printf "start test_dep_web\nquit\n" | ./taskmasterctl
# Expected Error: cannot start 'test_dep_web': dependencies not RUNNING (test_dep_db)

# 2. Start the dependency (has starttime = 3)
printf "start test_dep_db\nquit\n" | ./taskmasterctl

# 3. Wait for test_dep_db to achieve RUNNING state
sleep 3.5

# 4. Now start dependent service -> MUST SUCCEED
printf "start test_dep_web\nquit\n" | ./taskmasterctl

# 5. Verify both are running
printf "status test_dep_db\nstatus test_dep_web\nquit\n" | ./taskmasterctl
```

---

### 3.4 Signal Routing & Forced Kill (`stopsignal` & `stoptime`)

`config.toml` includes diverse signal configurations:
- `test_sleep_int`: `stopsignal = "INT"`
- `test_sleep_quit`: `stopsignal = "QUIT"`
- `test_sleep_usr1`: `stopsignal = "USR1"`
- `test_ignore_term`: ignores `SIGTERM`, has `stoptime = 3` (forced `SIGKILL`).

```bash
# Stop test_ignore_term: daemon will send SIGTERM, wait 3 seconds, then send SIGKILL
printf "stop test_ignore_term\nquit\n" | ./taskmasterctl
```

Verify in `logs/taskmaster.log`:
```bash
tail -n 10 logs/taskmaster.log | grep test_ignore_term
```
**Expected in log:**
```text
WARNING  taskmasterd.test_ignore_term: Graceful stop timed out; force-killing process.
INFO     taskmasterd.test_ignore_term: SIGKILL sent.
INFO     taskmasterd.test_ignore_term: Stopped with exit code -9.
```

---

### 3.5 High Volume Output / OS Pipe Buffer Test (`test_flood`)

`test_flood` generates 500,000 lines instantly:
- Verifies that `taskmasterd` does not deadlock on OS pipe buffers (64 KB).
- Verifies output is cleanly written to `logs/flood.log`.

```bash
wc -l logs/flood.log
# Expected: ~500000 lines
```

---

### 3.6 Environment Variables & Umask Verification

```bash
# Check environment variables were applied
cat logs/env.log
# Expected: FOO=taskmaster_bar, APP_ENV=production

# Check umask 077 was applied
cat logs/umask.log
# Expected: -rw------- permissions
```

---

### 3.7 Hot-Reload (`reload` and `SIGHUP`)

Verify that reload keeps unchanged processes running without restarting them:

```bash
# Note down PIDs of running processes
printf "status test_workers\nquit\n" | ./taskmasterctl

# Trigger reload via IPC command
printf "reload\nquit\n" | ./taskmasterctl

# Or trigger reload via SIGHUP
kill -HUP $(pgrep -f "python3.*taskmasterd")

# Check status again: PIDs must remain identical (no respawn!)
printf "status test_workers\nquit\n" | ./taskmasterctl
```

---

## 4. Raw Socket Testing & Negative Testing (`netcat`)

The daemon communicates over `AF_UNIX` using UTF-8 NDJSON. Use OpenBSD `netcat` (`nc -U /tmp/taskmaster.sock`) for positive and negative protocol checks.

### 4.1 Positive Protocol Test
```bash
echo '{"command": "status", "target": "all"}' | nc -U /tmp/taskmaster.sock
```
**Expected Response:**
```json
{"ok": true, "data": {"programs": [...]}}
```

---

### 4.2 Negative Tests (RFC / Protocol Robustness)

#### Test N1: Malformed JSON Syntax
```bash
echo '{"command": "status"' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "MALFORMED_REQUEST", "message": "malformed JSON request line"}}
```

#### Test N2: Duplicate JSON Keys
```bash
echo '{"command": "status", "command": "stop"}' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "MALFORMED_REQUEST", "message": "duplicate JSON object key 'command'"}}
```

#### Test N3: Unexpected / Extra Fields
```bash
echo '{"command": "status", "foo": "bar"}' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "MALFORMED_REQUEST", "message": "unexpected field 'foo'"}}
```

#### Test N4: Unknown Command
```bash
echo '{"command": "invalid_cmd"}' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "UNKNOWN_COMMAND", "message": "unknown command 'invalid_cmd'"}}
```

#### Test N5: Missing Required Target
```bash
echo '{"command": "start"}' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "INVALID_ARGUMENT", "message": "command 'start' requires a target"}}
```

#### Test N6: Forbidden Target
```bash
echo '{"command": "reload", "target": "all"}' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "INVALID_ARGUMENT", "message": "command 'reload' does not accept a target"}}
```

#### Test N7: Non-existent Target
```bash
echo '{"command": "start", "target": "does_not_exist"}' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "UNKNOWN_TARGET", "message": "program 'does_not_exist' is not configured"}}
```

#### Test N8: Oversized Request (> 65,536 bytes)
```bash
python3 -c 'print("{\"command\": \"" + "a"*70000 + "\"}")' | nc -U /tmp/taskmaster.sock
```
**Expected Error:**
```json
{"ok": false, "error": {"code": "REQUEST_TOO_LARGE", "message": "request exceeds 65536 bytes"}}
```

---

## 5. Clean Shutdown & Post-Run Cleanup

Send `shutdown` command to gracefully stop all programs, drain sockets, and terminate `taskmasterd`:

```bash
printf "shutdown\n" | ./taskmasterctl
```

**Verify Clean State:**
```bash
# 1. Daemon process terminated
pgrep -fl taskmasterd

# 2. No orphan or zombie child processes left
ps aux | grep -E "sleep 300|sleep 30|http.server" | grep -v grep

# 3. Socket file removed
ls -l /tmp/taskmaster.sock
```

**Expected Outcome:**
- `pgrep` returns empty.
- No orphan processes remain.
- `/tmp/taskmaster.sock` is deleted.
