# Taskmaster IPC protocol

`taskmasterd` and `taskmasterctl` communicate through the Unix-domain stream
socket configured as `socket_path` (default: `/tmp/taskmaster.sock`).  The
socket is local-only: the daemon creates it with mode `0600`.

## Transport and framing

- The protocol is UTF-8 encoded JSON Lines (NDJSON): exactly one JSON object
  per line, terminated by a single LF (`\n`).
- A client opens one connection, sends one request line, reads one response
  line, and closes the connection.  The daemon closes its side after writing
  the response.  A closed connection is not a message delimiter.
- The maximum encoded request or response, including its terminating LF, is
  65,536 bytes.  Oversized or malformed requests receive an error when a
  response can safely be written; otherwise the server closes the connection.
- The server must tolerate fragmented reads and writes.  It must reject a
  second request on the same connection rather than executing it.

## Request object

Every request has this shape:

```json
{"id": "b926ae9c", "command": "status", "target": "all"}
```

| Field | Required | Rules |
| --- | --- | --- |
| `id` | yes | Non-empty string of at most 64 characters. It is opaque and is echoed unchanged in the response. |
| `command` | yes | One of the commands below, lowercase ASCII. |
| `target` | depends | Program-group name, process-instance name, or the literal `"all"`. |

Unknown fields are rejected.  This prevents a newer client from silently
assuming semantics an older daemon does not implement.

## Commands

| Command | `target` | Meaning |
| --- | --- | --- |
| `status` | optional; default `"all"` | Return the current state of the selected program(s). |
| `start` | required | Start every stopped process in the selected program(s). Running or starting processes are left unchanged. |
| `stop` | required | Request graceful stop of every selected active process. The response confirms the request; it does not wait for process exit. |
| `restart` | required | Request stop, then start each selected process on the first daemon tick after it reaches a terminal state. It does not start a replacement while the old process is still stopping. |
| `reload` | forbidden | Reload the daemon configuration using the same behavior as `SIGHUP`. |
| `shutdown` | forbidden | Request orderly daemon shutdown. The daemon stops managed programs and removes its socket. |
| `help` | forbidden | Return supported commands and their short descriptions. |

`target: "all"` is permitted for `start`, `stop`, and `restart`. A group
target affects all its instances. A process target, such as `worker_0`,
affects only that instance. A group restart may therefore restart its
instances at different times. If a configured group name equals an instance
name in another group, the group name takes precedence.

## Successful response

```json
{"id": "b926ae9c", "ok": true, "data": {"programs": []}}
```

All successful responses contain `id`, `ok: true`, and `data`.
For an action command, `data` contains at least `{"accepted": ["name"]}`;
the names are the affected program-group names, including when a single
process instance was targeted.
For `status`, it contains this stable representation:

```json
{
  "programs": [
    {
      "name": "worker",
      "processes": [
        {
          "name": "worker_0",
          "state": "RUNNING",
          "pid": 1234,
          "uptime_seconds": 42.3,
          "exit_code": null
        }
      ]
    }
  ]
}
```

`pid`, `uptime_seconds`, and `exit_code` are `null` when not applicable.
`state` is the uppercase `ProcessState` name.  Programs appear in their
configuration order; processes appear in instance order.

## Error response

```json
{
  "id": "b926ae9c",
  "ok": false,
  "error": {"code": "UNKNOWN_TARGET", "message": "program 'api' is not configured"}
}
```

The response uses the supplied `id` if it was valid; otherwise it is `null`.
The client must treat `message` as display text only and branch on `code`.

| Code | Meaning |
| --- | --- |
| `MALFORMED_REQUEST` | Invalid UTF-8, JSON, object shape, or unexpected field. |
| `UNKNOWN_COMMAND` | `command` is not implemented. |
| `INVALID_ARGUMENT` | A command has a missing, forbidden, or invalid target. |
| `UNKNOWN_TARGET` | The named program group or process does not exist in the active configuration. |
| `REQUEST_TOO_LARGE` | The request exceeds the protocol size limit. |
| `COMMAND_FAILED` | A valid command could not be accepted or completed. |
| `INTERNAL_ERROR` | Unexpected daemon error; details are written only to the daemon log. |

Socket connection errors are client-side failures, not protocol responses:
`taskmasterctl` must report a clear message and exit non-zero when the socket
is absent, refused, or times out.

## CLI mapping

`taskmasterctl` maps shell input without invoking a shell:

```text
status [GROUP|PROCESS]
start GROUP|PROCESS|all
stop GROUP|PROCESS|all
restart GROUP|PROCESS|all
reload
shutdown
help
quit
```

`quit` only exits the interactive client; `shutdown` stops the daemon.
Arguments are parsed with `shlex.split`, and the client sends the resulting
structured request.  The daemon never executes user-supplied command text.
