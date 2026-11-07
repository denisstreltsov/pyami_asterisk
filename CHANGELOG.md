# Changelog

## Unreleased

### Fixed

- Reconnect is one loop inside `connect_ami()`: no recursion, so a long-running client no longer ends
  with `RecursionError` after many drops.
- Ping and `create_action(..., repeat=N)` run in exactly one copy after a reconnect (1.5.2 started one more
  copy on every reconnect).
- The previous socket is closed when the connection ends, including after `Event: Shutdown`.
- Actions still waiting for an answer when the connection ends are dropped with a log line.
- Fractional `reconnect_timeout`, `reconnect_timeout_increase` and `ping_delay` work (1.5.2 truncated them
  with `int()`, so `reconnect_timeout=0.5` silently disabled reconnecting).
- After a connection that dropped sooner than `reconnect_timeout` the client pauses before reconnecting,
  so a PBX that drops right after login does not get a tight loop.

- `IdGenerator` no longer keeps every instance in the class-level `instances` list; the client uses one
  generator. 1.5.2 leaked one object per action, Ping included (~17 000 a day with the default `ping_delay`).

- A key repeated in a packet keeps every value in order; 1.5.2 lost the first one and mixed the values of
  different repeated keys into one shared list.
- A line without `": "` no longer crashes the parser: `Key:` is an empty value, raw text (legacy `Command`
  output) is collected under `Output`.
- `ActionID`, `Event: Shutdown` and `Response: Goodbye` are recognised by parsed fields, not by a substring
  anywhere in the packet (the word `ActionID` in any value crashed the client with `KeyError`).
- Packets longer than the read buffer are read whole; 1.5.2 broke the framing of the rest of the stream.

- Non-string values in an action are written as text (`True`/`False` as `true`/`false`); 1.5.2 raised
  `TypeError`. A `None` value leaves the key out.
- A key or value containing CR or LF is refused with `ValueError` (in `create_action` and before anything is
  written): it could inject extra lines, even a whole action, into the packet.

- The answer to `Login` is awaited with a timeout (`login_timeout`, 10 s); a silent PBX no longer hangs the
  client forever.
- A connection that drops or times out during login is a failed attempt retried after the usual pause; 1.5.2
  raised `IncompleteReadError` out of `connect_ami()`. A refused login still stops, as in 1.5.2.
- The banner and the login answer are parsed by fields, not by line positions; events before the answer are
  skipped.

### Added

- `reconnect_timeout_max`: upper bound of the pause grown by `reconnect_timeout_increase`.
- `login_timeout`: seconds to wait for the answer to `Login` (default 10).
- `buffer_limit`: read buffer size in bytes (default 64 KiB as in 1.5.2).

### Changed

- `reconnect_timeout=0` means no reconnect at all; 1.5.2 made one immediate attempt before giving up.

### Development

- Fake AMI server for tests, `pytest>=8`, GitHub Actions on Python 3.10-3.14; Travis CI removed.
