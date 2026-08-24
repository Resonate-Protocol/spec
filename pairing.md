## Pairing

Pairing is the one-time setup that mutually authenticates a client and a server. The pairing flow uses the same WebSocket endpoint and [`KKpsk2`](connection.md#encryption) Noise pattern as every other connection; only the PSK fed into the handshake and the client's post-handshake routing differ (see [Pre-Shared Key](connection.md#pre-shared-key)). After any successful pairing both sides persist the new pairing record, then the server initiates an in-band [re-handshake](connection.md#re-handshake) to the newly delivered `long_term_psk`, bringing the channel to the new trust level without closing the WebSocket.

This specification defines three pairing methods. Servers must implement all three; clients must implement Pairing PSK and may additionally implement either or both pairing-code methods.

### Methods

1. **Pairing PSK** - pairing authenticated by a [pairing PSK](README.md#definitions); no PAKE round, no pairing code. See [Pairing PSK Flow](#pairing-psk-flow).
2. **Dynamic Pairing Code** - pairing with a per-session [Pairing Code](README.md#definitions) that the client derives from a commit-and-reveal binding to the Noise handshake and emits via an out-channel (display, speaker, etc.) for the operator to enter into the server. See [Dynamic Pairing Code Flow](#dynamic-pairing-code-flow).
3. **Static Pairing Code** - pairing with a fixed [Pairing Code](README.md#definitions). Appropriate for devices with no out-channel; vulnerable to MITM if the pairing code is disclosed. See [Static Pairing Code Flow](#static-pairing-code-flow).

- **Unpaired.** Sentinel PSK; the channel is unauthenticated until the CPace round completes. The round establishes trust from scratch and produces a new [long-term PSK](README.md#definitions).
- **Already paired.** The server moves the established connection into pairing (see [Entering and leaving pairing](#entering-and-leaving-pairing)) and runs the round over the existing long-term PSK.

The client reveals the new PSK only after `server_kc` verifies, and only as `wrapped_psk` [sealed under the CPace output](#wrapping): a peer that cannot complete the PAKE - wrong pairing code, or a man in the middle relaying between two handshakes, whose differing `h` gives each leg a different `sid` - neither triggers the reveal nor can unwrap it.

Static pairing methods (Pairing PSK, Static Pairing Code) do not take over the device's out-channel. Dynamic pairing (Dynamic Pairing Code) takes over the out-channel - typically the audio output or display - to emit the per-session pairing code, so it cannot run while audio is playing on the same device. A pairing attempt that arrives while another connection is playing is rejected (see [Multiple servers](connection.md#multiple-servers-server-initiated)); the operator must stop playback before initiating pairing.

Clients with a usable out-channel (display, speaker, etc.) SHOULD implement `dynamic_pairing_code` and prefer it to `static_pairing_code` - but SHOULD implement `static_pairing_code` too, shipped [disabled](management.md#server--client-managementset-pairing-config) with no pairing code provisioned. Clients whose display can render a QR code SHOULD also offer the `qr_code` [emission format](#dynamic-pairing-code-flow).

### Entering and leaving pairing

Pairing and playback are mutually exclusive on a connection. When a server moves an established connection into pairing it first quiesces the client's streams - sending [`stream/end`](messaging.md#server--client-streamend) for active stream roles and a [`server/state`](messaging.md#server--client-serverstate) with null role objects for state roles, as when a role is removed from `active_roles` - and then sends the pairing [`server/activate`](messaging.md#server--client-serveractivate) with empty `active_roles`. The quiesce is stream-only: unlike an [`available: false`](messaging.md#external-source-handling) transition, the client keeps its group membership and queued group state through the pairing activity - no move to a solo group, no previous-group memory, no bar on resuming in place.

Each pairing `server/activate` admits one **pairing attempt**, in progress from its first pairing message - [`client/pair-init`](#client--server-clientpair-init) (pairing-code methods) or [`client/pair-finalize`](#client--server-clientpair-finalize) (Pairing PSK) - until success or [`pair/abort`](#client--server-pairabort). [`client/pair-pending`](#client--server-clientpair-pending) precedes an attempt and does not start it. The client bounds each attempt with an **attempt timeout** measured from its first message (recommended 2 minutes); on expiry it sends `pair/abort` with reason `attempt_timeout`.

The `server/activate` that ends the pairing transition declares the connection's resulting `activities` and reactivates roles via `active_roles`.

The same `server/activate` can also end a pairing attempt without finalizing: sent in place of [`server/pair-finalize`](#server--client-serverpair-finalize), it persists nothing and discards any received PSK. A client that, after sending [`client/pair-finalize`](#client--server-clientpair-finalize), receives `server/activate` likewise persists nothing.

After leaving pairing, a server silently discards pairing messages still in flight from the client - messages sent before the client observed the leave `server/activate`. A client that has aborted an attempt likewise silently discards pairing messages received before the next `server/activate`.

A server MAY send such a cancelling `server/activate` at any point during a pairing attempt. On receipt the client abandons the attempt, discarding all pairing state, and proceeds under the declared activities; an abandoned attempt is not an inner-authentication failure and does not touch the [failure counter](#failure-counter). A server cancelling on operator action SHOULD first send [`pair/abort`](#client--server-pairabort) with reason `user_cancelled`, so the client can surface why the attempt ended. Servers SHOULD apply their own timeout while waiting for the attempt's first pairing message - [`client/pair-init`](#client--server-clientpair-init) or, in the Pairing PSK Flow, [`client/pair-finalize`](#client--server-clientpair-finalize) - cancelling as above on expiry.

### Unpaired Access

A client MAY admit a server with no pairing record to activate roles or declare the `'playback'` activity. The session's [trust level](README.md#definitions) is `'none'`, so [management](management.md#management) operations remain unavailable. Servers SHOULD consider their role-activation policy on such sessions in light of the MITM exposure described below. The default is the manufacturer's choice. The client's toggle is exposed at runtime via [`management/set-pairing-config`](management.md#server--client-managementset-pairing-config), and its current setting is advertised in [`client/hello`](messaging.md#client--server-clienthello) as `unpaired_access.enabled`. Servers must likewise allow their operator to enable or disable offering unpaired access. The offer is conveyed to the client through [`active_roles`](messaging.md#server--client-serveractivate), not a separate flag.

**Security.** Unpaired playback connections are vulnerable to **man-in-the-middle attacks**. The Sentinel PSK is a published constant, and in the unpaired case neither peer's static key is bound to its identity by any authenticated out-of-band exchange; an attacker on the local network may therefore impersonate either side. The Noise handshake still provides confidentiality and replay protection for the session itself, but offers no assurance about which peer it was established with.

### Pairing PSK Flow

The Noise handshake completes using the pairing PSK, authenticating both sides. The client proceeds straight to [`client/pair-finalize`](#client--server-clientpair-finalize).

**Lifecycle.** The client's pairing PSK is generated from a CSPRNG per device - never a shared default - provisioned at manufacture or generated by the client, and persists across reboots. It is per-client and long-lived: a successful pairing does not consume or rotate it (pairing produces a separate [long-term PSK](README.md#definitions)), so it can pair the client with any number of servers. The client MUST NOT rotate it on its own; rotation happens through a deliberate local operator action (manufacturer-defined) or via [`management/set-pairing-config`](management.md#server--client-managementset-pairing-config) (`pairing_psk.psk`) from a paired server. Rotation invalidates previously distributed copies but leaves established pairing records untouched.

```mermaid
sequenceDiagram
    participant Client
    participant Server

    Note over Client,Server: Noise handshake completes with the pairing PSK

    Server->>Client: server/hello (name)
    Client->>Server: client/hello (supported_pair_methods)
    Server->>Client: server/activate (activities=['pairing'], active_roles=[], pairing={method: pairing_psk})
    Client->>Server: client/pair-finalize (long_term_psk)
    Server->>Client: server/pair-finalize
    Note over Client,Server: Both sides persist the pairing record. Server re-handshakes to the new PSK.
```

If a connection is already open under any other PSK - Sentinel or a [long-term PSK](README.md#definitions) - when the operator picks `pairing_psk`, the server first [re-handshakes](connection.md#re-handshake) to the pairing PSK before sending the `server/activate` shown above.

Two standing client obligations follow from this flow:

1. The client MUST keep its pairing PSK among its handshake PSK candidates whenever the method is [enabled](management.md#server--client-managementset-pairing-config), not only while a pairing activity is running: the server's re-handshake to the pairing PSK succeeds only if the client already recognizes its `psk_id`.
2. Before sending [`client/pair-finalize`](#client--server-clientpair-finalize), the client MUST verify that the connection's matched PSK is the pairing PSK (the receiving side of the `pairing.method` invariant in [`server/activate`](messaging.md#server--client-serveractivate)); on mismatch it aborts with [`pair/abort`](#client--server-pairabort) reason `method_not_supported`.

**Pairing Token.** A server needs both the [pairing PSK](README.md#definitions) and the client's static public key to select and verify the client's Noise identity. The two are distributed together in a version-0 [pairing token](#pairing-token):

```
payload = client_key (32 bytes) || pairing_psk (32 bytes)
```

- `client_key` - the raw 32-byte Curve25519 public key whose base64url form is the [`client_id`](connection.md#identities).
- `pairing_psk` - the raw 32-byte [pairing PSK](README.md#definitions).

The operator enters the token into the server to begin the flow. The pairing PSK MUST be exposed as the token, not the bare PSK. Before pairing, the server MUST confirm the decoded `client_key` matches the `client_id` presented on the connection.

The reference vector for `client_key = 0x00 0x01 … 0x1f` and `pairing_psk = 0xe0 0xe1 … 0xff`:

```
SP:0AAAQEAYEAUDAOCAJBIFQYDIOB4IBCEQTCQKRMFYYDENBWHA5DYP6BYPC4PSOLZXH5DU6V97M5XXO74HR6LZ7J5PW674PT6X37T6757Y
```

### Dynamic Pairing Code Flow

Pairing with a per-session pairing code derived from the Noise handshake and emitted by the client via its out-channel, in one of two **emission formats** (the activation's [`format`](messaging.md#server--client-serveractivate)): `digits` - a decimal code the operator types into the server - or `qr_code` - a code rendered as a QR code that the operator scans into the server. Either way, a [PAKE](#pake) round authenticates both sides. An attempt is gesture-gated only when the method is [escalated](#failure-counter) (see [Pairing Window](#pairing-window)).

```mermaid
sequenceDiagram
    participant Client
    participant Server

    Note over Client,Server: Noise handshake completes (Sentinel PSK when unpaired, long-term PSK when re-verifying a paired device)

    Server->>Client: server/hello (name)
    Client->>Server: client/hello (supported_pair_methods)
    Note over Server: Operator picks dynamic pairing code
    Server->>Client: server/activate (activities=['pairing'], active_roles=[], pairing={method: dynamic_pairing_code})
    opt gesture-gated attempt, no window open
        Client->>Server: client/pair-pending
        Note over Client: Operator opens pairing window
    end
    Client->>Server: client/pair-init (commit_B)
    Server->>Client: server/pair-init (nonce_A)
    Note over Client: Derive pairing code from (h, nonce_A, nonce_B), emit via out-channel
    Note over Server: Operator enters pairing code
    Server->>Client: server/pair-auth (pake_msg_1)
    Client->>Server: client/pair-auth (pake_msg_2)
    Server->>Client: server/pair-confirm (server_kc)
    Note over Client: Verify server_kc
    Client->>Server: client/pair-confirm (client_kc, wrapped_nonce_B)
    Note over Server: Verify client_kc, commit opening, and pairing code binding
    Note over Client: Sent back-to-back, no server response awaited
    Client->>Server: client/pair-finalize (wrapped_psk)
    Server->>Client: server/pair-finalize
    Note over Client,Server: Both sides persist the pairing record. Server re-handshakes to the new PSK.
```

**Binding values.** The Dynamic Pairing Code Flow introduces three values across two messages that bind the pairing code to the underlying Noise handshake:

- `nonce_A` - 32 bytes drawn from a CSPRNG by the server, sent in [`server/pair-init`](#server--client-serverpair-init), base64url-encoded (43 chars).
- `nonce_B` - 32 bytes drawn from a CSPRNG by the client, kept private until [`client/pair-confirm`](#client--server-clientpair-confirm) reveals it as `wrapped_nonce_B`, [sealed under the CPace output](#wrapping).
- `commit_B` - `SHA-256("sendspin-pair-commit-v1" || nonce_B)`, sent by the client in [`client/pair-init`](#client--server-clientpair-init) before any value from the server is known (32 bytes base64url-encoded, 43 chars). Locks the client's contribution to the pairing code derivation.

**Pairing code derivation.** Both formats derive the pairing code from the same digest of the Noise handshake hash `h` and the two nonces:

```
digest   = SHA-256("sendspin-pairing-code-derive-v1" || h || nonce_A || nonce_B)

digits:   code_int = uint256_be(digest) mod 10^6
          code     = decimal(code_int) zero-padded to 6 digits
qr_code:  code     = digest[0..23]
```

The hash input is the UTF-8 bytes of the literal label `"sendspin-pairing-code-derive-v1"` (no separator, no NUL terminator) followed by `h` (32 bytes, raw), `nonce_A` (32 bytes, raw), and `nonce_B` (32 bytes, raw). In the `digits` format the full 32-byte SHA-256 output is interpreted as an unsigned big-endian 256-bit integer and reduced modulo 10^6, zero-padded on the left to exactly 6 ASCII digits. The pairing code bytes fed into CPace as `PRS` are these 6 ASCII digits - the same per-digit encoding as the static pairing code. In the `qr_code` format the pairing code is binary - the first 24 bytes of the digest - and the code bytes fed into CPace as `PRS` are these 24 raw bytes.

**Digits emission.** When emitting the pairing code through a spoken channel, the client SHOULD use the best-matching language it supports, treating the activation's [`languages`](messaging.md#server--client-serveractivate) as the language priority list under [RFC 4647](https://www.rfc-editor.org/rfc/rfc4647#section-3.4) Lookup matching, and falling back to its own default when nothing matches. The hint is informational and never grounds for [`pair/abort`](#client--server-pairabort); display emission is unaffected. Spoken emission SHOULD read single digits in the [presentation groups](#pairing-code-presentation), pausing between groups.

**QR-code emission.** In the `qr_code` format the client presents the pairing code as a version-1 [pairing token](#pairing-token) with the 24-byte code as its payload (39 body characters), rendered as a QR code on its display. The server applies the token [decoding](#pairing-token) rules to operator input; the first 24 payload bytes are the entered pairing code.

The reference vector for `code = 0xe0 0xe1 … 0xf7`:

```
SP:14DQ6FY7E4XTOP9HJ5LV6Z3PO57YPD4XT6T97N5Y
```

**Client verification.** On receipt of [`server/pair-confirm`](#server--client-serverpair-confirm), the client verifies the CPace MCF tag `server_kc`. On failure the client sends [`pair/abort`](#client--server-pairabort) with reason `pairing_code_mismatch`.

**Server verification.** When [`client/pair-confirm`](#client--server-clientpair-confirm) arrives, the server verifies, in this order:

1. CPace MCF tag `client_kc`
2. `wrapped_nonce_B` [unwraps](#wrapping) to a `nonce_B` with `SHA-256("sendspin-pair-commit-v1" || nonce_B) == commit_B`
3. `derived_code(h, nonce_A, nonce_B) == code_entered`

A failed key confirmation results in [`pair/abort`](#client--server-pairabort) with reason `pairing_code_mismatch`. A `wrapped_nonce_B` that fails to decrypt, a recovered `nonce_B` that does not match `commit_B`, or an entered code that fails the binding check is a [protocol error](#protocol-errors). Any failure discards the received `wrapped_psk`. Only when all three checks pass does the server process [`client/pair-finalize`](#client--server-clientpair-finalize), [unwrapping](#wrapping) the PSK.

**Device-presence verification.** When the server [leaves pairing](#entering-and-leaving-pairing) instead of finalizing, this flow doubles as a device-presence verification: the pairing code is emitted through the device's own out-channel, so a successful round confirms the device on the connection is the one the operator is observing - useful on top of static pairing methods, which establish cryptographic identity but do not bind it to a specific physical device.

#### Failure counter

Brute-force protection for the Dynamic Pairing Code Flow is built around a failure counter that escalates the method to gesture-gating (see [Pairing Window](#pairing-window)). The following rules are mandatory for clients implementing `dynamic_pairing_code`:

- **Counter.** The client maintains a single failure counter for the method, persisted across reboots. It is not partitioned by `server_id` or source IP.
- **Increment.** The counter increments on each inner-authentication failure the client itself detects: its own verification of `server_kc` fails. No other event increments it.
- **Reset.** The counter resets to zero when the client's verification of `server_kc` succeeds, whether or not the attempt finalizes.
- **Escalation.** When the counter reaches **10**, the method is **escalated**: every subsequent attempt is gesture-gated until a reset de-escalates it. Escalation is not an error state - the method stays offered.

### Static Pairing Code Flow

Pairing with a fixed pairing code. The operator types it into the server, where a [PAKE](#pake) round authenticates both sides. Every attempt is gesture-gated by a [pairing window](#pairing-window).

**Lifecycle.** The static pairing code is a fixed 8-digit value. A factory-provisioned pairing code MUST be randomly generated per device and MUST NOT be a fixed default shared across devices; a shared default would let anyone pair with any such device. The client MUST NOT rotate it on its own; rotation happens through a deliberate local operator action (manufacturer-defined) or via [`management/set-pairing-config`](management.md#server--client-managementset-pairing-config) (`static_pairing_code.code`) from a paired server. Rotation invalidates a previously printed or distributed pairing code but leaves established pairing records untouched.

```mermaid
sequenceDiagram
    participant Client
    participant Server

    Note over Client,Server: Noise handshake completes (Sentinel PSK when unpaired, long-term PSK when re-verifying a paired device)

    Server->>Client: server/hello (name)
    Client->>Server: client/hello (supported_pair_methods)
    Note over Server: Operator picks static pairing code
    Server->>Client: server/activate (activities=['pairing'], active_roles=[], pairing={method: static_pairing_code})
    opt no window open
        Client->>Server: client/pair-pending
        Note over Client: Operator opens pairing window
    end
    Client->>Server: client/pair-init
    Note over Server: Operator enters static pairing code
    Server->>Client: server/pair-auth (pake_msg_1)
    Client->>Server: client/pair-auth (pake_msg_2)
    Server->>Client: server/pair-confirm (server_kc)
    Note over Client: Verify server_kc
    Client->>Server: client/pair-confirm (client_kc)
    Note over Server: Verify client_kc
    Note over Client: Sent back-to-back, no server response awaited
    Client->>Server: client/pair-finalize (wrapped_psk)
    Server->>Client: server/pair-finalize
    Note over Client,Server: Both sides persist the pairing record. Server re-handshakes to the new PSK.
```

**Client verification.** On receipt of [`server/pair-confirm`](#server--client-serverpair-confirm), the client verifies the CPace MCF tag `server_kc`. On failure the client sends [`pair/abort`](#client--server-pairabort) with reason `pairing_code_mismatch`.

**Server verification.** When [`client/pair-confirm`](#client--server-clientpair-confirm) arrives, the server verifies the CPace MCF tag `client_kc` before processing [`client/pair-finalize`](#client--server-clientpair-finalize). On failure the server sends [`pair/abort`](#client--server-pairabort) with reason `pairing_code_mismatch` and discards the received `wrapped_psk`. On success it processes `client/pair-finalize`, [unwrapping](#wrapping) the PSK.

### Pairing Code Presentation

Grouping is presentation-only: the pairing code value is the contiguous digits, and separators never enter derivation, entry, or `PRS`. The 6-digit dynamic pairing code SHOULD be presented grouped `3-3`, the 8-digit static pairing code `4-4`, with a hyphen between groups (`123-456`, `1234-5678`). Servers SHOULD present matching grouped entry that makes the expected length evident (e.g. one slot per digit) and SHOULD strip separator characters (spaces, hyphens) from typed input.

### Pairing Token

A **pairing token** is a single case-insensitive ASCII string carrying a pairing secret, which the operator transfers out of band (copy/paste, QR scan) from the client into the server. A token is a fixed `SP:` prefix, a version, and a base32-encoded body:

```
token = "SP:" || version || body
```

- `version` - a single alphanumeric character selecting the payload the body carries. This document defines version `0` - a [pairing PSK with the client identity](#pairing-psk-flow) - and version `1` - a per-session [dynamic pairing code](#dynamic-pairing-code-flow) in the `qr_code` emission format.

A payload becomes `body` by:

1. base32-encoding it per [RFC 4648](https://www.rfc-editor.org/rfc/rfc4648#section-6) (alphabet `A–Z`, `2–7`),
2. stripping the `=` padding, then
3. transliterating every `2` to `9`.

Tokens are drawn only from the QR code alphanumeric set (`0–9`, `A–Z`, `:`), so they render as compact QR codes and survive manual transcription. A QR code carries the token string verbatim, with no URI scheme or wrapper, so a scan and a copy/paste yield identical input.

Decoding reverses the transform and MUST be lenient with operator-supplied input:

1. Trim surrounding whitespace and upper-case it.
2. If present, strip a leading `SP:`. The first character is the `version`; reject an unrecognized version. An interface that accepts several versions dispatches on this character; one expecting a specific version rejects the others.
3. Transliterate every `9` back to `2`, re-pad with `=` to a multiple of 8 characters, and base32-decode into the payload.

A decoder MUST reject malformed input, including a payload shorter than its version defines. Payload bytes beyond those the version defines are reserved for future extension: a decoder MUST ignore them.

### Pairing Window

Code-based pairing gates some attempts on a **pairing window**: a state in which the client has decided to accept one pairing attempt. The window admits exactly one attempt and closes on completion, inner-authentication failure, [`pair/abort`](#client--server-pairabort), drop of the connection carrying its attempt, operator cancellation, window-lifetime expiry, or attempt-timeout expiry.

An attempt is **gesture-gated** - the client withholds [`client/pair-init`](#client--server-clientpair-init) until a window is open - per the selected method's policy:

- `static_pairing_code` - every attempt.
- `dynamic_pairing_code` - only when the method is [escalated](#failure-counter).

Pairing Window mechanics:

- **Opening the window.** An operator gesture on the client - a physical button press, a reset-pinhole press, a button combo, a specific power-cycle pattern, a shake or motion gesture, or any equivalent implementation-defined action - or a paired server via [`management/open-pairing-window`](management.md#server--client-managementopen-pairing-window). Gestures SHOULD be deliberate and hard to induce remotely.
- **Window lifetime.** From window opening until [`client/pair-init`](#client--server-clientpair-init) is sent. Recommended 5 minutes. On expiry, the window closes silently.
- **Signal to the server.** The client sends [`client/pair-init`](#client--server-clientpair-init) once the window is open and the [`server/activate`](messaging.md#server--client-serveractivate) has arrived; while a gesture is awaited it signals [`client/pair-pending`](#client--server-clientpair-pending). The server must not send [`server/pair-auth`](#server--client-serverpair-auth) until it has received `client/pair-init`.

### PAKE

The code-based pairing flows use **CPACE-X25519-SHA512** as the PAKE construction, defined in [draft-irtf-cfrg-cpace-21](https://datatracker.ietf.org/doc/draft-irtf-cfrg-cpace/21/). The protocol runs in initiator-responder mode with explicit Mutual Confirmation Flow (MCF). The server takes role `A` (initiator); the client takes role `B` (responder).

Sendspin instantiates CPace's inputs as follows:

- `PRS` - the pairing code as a byte string: the literal decimal digits as UTF-8 (e.g., `0x31 0x32 0x33 0x34 0x35 0x36 0x37 0x38` for the pairing code `"12345678"`), or in the `qr_code` emission format the raw 24-byte code.
- `sid` - the UTF-8 bytes `"sendspin-pair-pake-v1"` || `h` || `counter`. `h` is the Noise handshake hash (32 bytes, raw) available immediately after Noise transport mode begins; `counter` is the number of pairing [`server/activate`](messaging.md#server--client-serveractivate) messages sent since the last Noise handshake, encoded as a big-endian uint32 (4 bytes).
- `CI` - empty.
- `ADa` - the UTF-8 bytes `"server"`.
- `ADb` - the UTF-8 bytes `"client"`.

The four pairing message fields carry the corresponding CPace values, base64url-encoded without padding:

| Sendspin field | Carried in | CPace value | Bytes | base64url length |
|---|---|---|---|---|
| `pake_msg_1` | [`server/pair-auth`](#server--client-serverpair-auth) | `Ya` (server's public share) | 32 | 43 |
| `pake_msg_2` | [`client/pair-auth`](#client--server-clientpair-auth) | `Yb` (client's public share) | 32 | 43 |
| `server_kc` | [`server/pair-confirm`](#server--client-serverpair-confirm) | `Ta` (server's MCF tag, HMAC-SHA-512) | 64 | 86 |
| `client_kc` | [`client/pair-confirm`](#client--server-clientpair-confirm) | `Tb` (client's MCF tag, HMAC-SHA-512) | 64 | 86 |

### Wrapping

In the code-based flows, two values cross the wire only sealed under the CPace output: the new PSK, carried as `wrapped_psk` in [`client/pair-finalize`](#client--server-clientpair-finalize), and - in the Dynamic Pairing Code Flow - the commitment opening `nonce_B`, carried as `wrapped_nonce_B` in [`client/pair-confirm`](#client--server-clientpair-confirm). Both sides derive a key per field:

```
K_wrap = SHA-256(label || sid || ISK)
```

with `label` `"sendspin-pair-psk-wrap-v1"` for `wrapped_psk` and `"sendspin-pair-nonce-wrap-v1"` for `wrapped_nonce_B`. The hash input is the UTF-8 bytes of the literal label (no separator, no NUL terminator) followed by `sid` (the CPace session id defined in [PAKE](#pake), raw) and `ISK` (the 64-byte CPace intermediate session key, raw). To wrap, the client encrypts the 32-byte value with the AEAD of the connection's negotiated [cipher suite](connection.md#cipher-suites), key `K_wrap`, a 12-byte all-zero nonce, and empty associated data; the field carries the 48-byte ciphertext-plus-tag, base64url-encoded without padding (64 chars). To unwrap, the server decrypts with the same AEAD, key, and nonce, recovering the 32-byte value.

### Protocol Errors

A condition during pairing that no conformant peer produces - a malformed or missing field, a CPace share with the wrong length or encoding a low-order point, a revealed nonce that does not match its commitment, an entered code that fails the binding check, a `wrapped_nonce_B` or `wrapped_psk` that fails to decrypt - is a **protocol error**: the detecting side closes the WebSocket without sending any application-level error message, and persists nothing.

### Client → Server: `client/hello` pair-method descriptor

Each entry in `supported_pair_methods` in [`client/hello`](messaging.md#client--server-clienthello) is a descriptor object that names the pairing method and advertises the kind of operator interaction the client expects so the server can render appropriate UX.

- `method`: 'dynamic_pairing_code' | 'pairing_psk' | 'static_pairing_code' - the pairing method identifier.
- `out_channels?`: ('display' | 'speaker')[] - informational hint for `dynamic_pairing_code` only, listing the channels through which the per-session pairing code is conveyed to the operator.
- `formats?`: ('digits' | 'qr_code')[] - the [emission formats](#dynamic-pairing-code-flow) the client offers. Required on `dynamic_pairing_code` descriptors, absent on others. Non-empty; `qr_code` requires a display able to render a QR code.
- `locations?`: ('device' | 'leaflet' | 'operator')[] - informational hint for `static_pairing_code` and `pairing_psk` only, listing where the operator can find the method's configured secret: printed on the device, on a leaflet in the box, or set by the operator. When the secret is rotated, the client updates the hint accordingly.

### Messages

The pairing messages below are listed in the order they appear in the Dynamic Pairing Code Flow (the most complete sequence). The Static Pairing Code Flow omits the [`server/pair-init`](#server--client-serverpair-init) message and the `commit_B` / `wrapped_nonce_B` fields; the Pairing PSK Flow additionally omits all `pair-pending`, `pair-init`, `pair-auth`, and `pair-confirm` messages.

**Sequence violations.** A pairing message that is out of sequence for the selected method and current state - and not covered by the silent-discard rules in [Entering and leaving pairing](#entering-and-leaving-pairing) - is a [protocol error](#protocol-errors).

**Pairing index.** [`client/pair-pending`](#client--server-clientpair-pending) and [`client/pair-init`](#client--server-clientpair-init) carry a `pairing_index` - the number of pairing [`server/activate`](messaging.md#server--client-serveractivate) messages received since the last Noise handshake. A value lower than the server's own count is a leftover from a superseded pairing and is discarded silently; a higher value is a [protocol error](#protocol-errors).

#### Client → Server: `client/pair-pending`

Reports that the selected attempt is gesture-gated and no [pairing window](#pairing-window) is open. Sent immediately on receiving such a pairing [`server/activate`](messaging.md#server--client-serveractivate); [`client/pair-init`](#client--server-clientpair-init) follows once a window opens. Does not start the [attempt](#entering-and-leaving-pairing) or its timeout. The server SHOULD surface the pending gesture to the operator and apply its own timeout (see [Entering and leaving pairing](#entering-and-leaving-pairing)).

- `pairing_index`: integer - see [Pairing index](#messages)

#### Client → Server: `client/pair-init`

Starts the code-based pairing [attempt](#entering-and-leaving-pairing). Sent once the pairing [`server/activate`](messaging.md#server--client-serveractivate) has arrived and - when the attempt is gesture-gated (see [Pairing Window](#pairing-window)) - a window is open; otherwise immediately. The server must not send [`server/pair-auth`](#server--client-serverpair-auth) (static pairing code) or [`server/pair-init`](#server--client-serverpair-init) (dynamic pairing code) before receiving this message.

- `pairing_index`: integer - see [Pairing index](#messages); only a match starts the attempt
- `commit_B?`: string - `SHA-256("sendspin-pair-commit-v1" || nonce_B)` (32 bytes base64url-encoded, 43 chars). Required in the [Dynamic Pairing Code Flow](#dynamic-pairing-code-flow); absent in the [Static Pairing Code Flow](#static-pairing-code-flow).

#### Server → Client: `server/pair-init`

Server's nonce contribution in the [Dynamic Pairing Code Flow](#dynamic-pairing-code-flow). Sent in response to [`client/pair-init`](#client--server-clientpair-init).

- `nonce_A`: string - 32 bytes from a CSPRNG, base64url-encoded (43 chars). See [Dynamic Pairing Code Flow](#dynamic-pairing-code-flow)

Upon receipt, the client derives and emits the pairing code; the operator then types or scans it into the server.

#### Server → Client: `server/pair-auth`

Server's CPace public share. Sent once the server has both received [`client/pair-init`](#client--server-clientpair-init) and obtained the pairing code from the operator. In the Static Pairing Code Flow the pairing code is available to the operator from the start; in the Dynamic Pairing Code Flow the client emits it after [`server/pair-init`](#server--client-serverpair-init).

- `pake_msg_1`: string - server's CPace public share `Ya` (32 bytes base64url-encoded, 43 chars). See [PAKE](#pake)

#### Client → Server: `client/pair-auth`

Client's CPace public share, sent in response to [`server/pair-auth`](#server--client-serverpair-auth).

- `pake_msg_2`: string - client's CPace public share `Yb` (32 bytes base64url-encoded, 43 chars). See [PAKE](#pake)

#### Server → Client: `server/pair-confirm`

Server's MCF tag, sent after the server has derived its CPace session key from `Yb`.

- `server_kc`: string - server's MCF tag `Ta` (64 bytes base64url-encoded, 86 chars). See [PAKE](#pake)

On receipt, the client verifies `server_kc` before sending [`client/pair-confirm`](#client--server-clientpair-confirm); see [Dynamic Pairing Code Flow](#dynamic-pairing-code-flow) / [Static Pairing Code Flow](#static-pairing-code-flow).

#### Client → Server: `client/pair-confirm`

Client's MCF tag, plus (in the Dynamic Pairing Code Flow) the sealed opening of the earlier commitment. In code-based pairing, the client sends [`client/pair-finalize`](#client--server-clientpair-finalize) immediately after this message without waiting for a server response.

- `client_kc`: string - client's MCF tag `Tb` (64 bytes base64url-encoded, 86 chars). See [PAKE](#pake)
- `wrapped_nonce_B?`: string - 48-byte [wrapping](#wrapping) of the preimage of `commit_B` sent earlier in [`client/pair-init`](#client--server-clientpair-init), base64url-encoded (64 chars). Present only in the [Dynamic Pairing Code Flow](#dynamic-pairing-code-flow).

On receipt, the server verifies before processing [`client/pair-finalize`](#client--server-clientpair-finalize); see [Dynamic Pairing Code Flow](#dynamic-pairing-code-flow) / [Static Pairing Code Flow](#static-pairing-code-flow).

#### Client → Server: `client/pair-finalize`

Delivers the long-term PSK established by this pairing. In flows that include a PAKE round, this message is sent immediately after [`client/pair-confirm`](#client--server-clientpair-confirm) without waiting for a server response, and carries the PSK [wrapped](#wrapping) under the CPace output. In the [Pairing PSK Flow](#pairing-psk-flow), it starts the pairing [attempt](#entering-and-leaving-pairing) and is sent immediately after the [`server/activate`](messaging.md#server--client-serveractivate), carrying the PSK directly. Exactly one of the two fields is present.

- `long_term_psk?`: string - 43-character base64url-encoded 32-byte [long-term PSK](README.md#definitions) (no padding). [Pairing PSK Flow](#pairing-psk-flow) only
- `wrapped_psk?`: string - 64-character base64url-encoded 48-byte [wrapping](#wrapping) of the new [long-term PSK](README.md#definitions) (no padding). Code-based flows only

#### Server → Client: `server/pair-finalize`

Acknowledges that the server has persisted the pairing record. After receiving this message, the client persists its own record.

- payload: `{}`

#### Client ↔ Server: `pair/abort`

Aborts a pairing attempt, started or not. With reason `concurrent_attempt` the sender closes the connection after sending, otherwise the connection stays open. A `pair/abort` received after the receiver has itself ended the attempt has no effect.

- `reason`: string - one of:
  - `attempt_timeout` (client) - the pairing attempt did not complete within the [attempt timeout](#entering-and-leaving-pairing)
  - `concurrent_attempt` (client) - another pairing attempt is already in progress with this client
  - `method_not_supported` (client) - the server's activity set and `pairing.method` are not a permitted combination for the matched PSK, or `pairing.method` names a method the client does not currently offer, or `pairing.format` names an emission format the client does not currently offer
  - `pairing_code_mismatch` (client or server) - PAKE key-confirmation failed
  - `user_cancelled` (client or server) - operator aborted the pairing through a local UI
