## Establishing a Connection

Sendspin has two standard ways to establish connections: Server and Client initiated. Server Initiated connections are recommended as they provide standardized multi-server behavior, but require mDNS which may not be available in all environments.

Servers must support both methods described below. Clients MUST use exactly one of the two methods at a time, advertising or discovering accordingly.

The WebSocket transport MUST be plain `ws://`. Confidentiality and integrity are provided end to end by the [Noise layer](#encryption) inside the WebSocket payloads.

### Server Initiated Connections

Clients announce their presence via mDNS using:
- Service type: `_sendspin._tcp.local.`
- Port: The port the Sendspin client is listening on (recommended: `8928`)
- TXT record: `path` key specifying the WebSocket endpoint, REQUIRED (recommended value: `/sendspin`)
- TXT record: `name` key specifying the friendly name of the player (optional)

The server discovers available clients through mDNS and connects to each client via WebSocket using the advertised address and path.

The TXT `name` SHOULD match the `name` the client sends in [`client/hello`](messaging.md#client--server-clienthello). It is only a discovery-time hint; if the two differ, the `client/hello` value is authoritative.

**Note:** Do not manually connect to servers if you are advertising `_sendspin._tcp`.

#### Multiple servers (server-initiated)

A client holds at most one admitted connection at a time, classified by the highest-ranked activity in its declared [`activities`](messaging.md#server--client-serveractivate); from highest to lowest:

- `'management'`
- `'playback'`
- `'pairing'`

A connection with empty `activities` ranks lowest.

Clients must persistently store the `server_id` of the server that most recently held the admitted connection while `'playback'` was among its `activities` (the "last-playback server").

When a new server connects, the client lets the handshake complete before applying admission; the new connection is provisional until its first [`server/activate`](messaging.md#server--client-serveractivate) declares its priority. The incoming connection's priority is compared to the current connection's: higher or equal is accepted, lower is rejected. Two exceptions:

- A [pairing attempt](pairing.md#entering-and-leaving-pairing) is not displaced by an incoming `'playback'` or `'pairing'` connection.
- When both the current holder and the incoming connection have empty `activities`, the incoming is admitted only if its `server_id` matches the last-playback server (and the existing one's does not); otherwise the existing is kept.

Subsequent `server/activate` updates do not trigger arbitration, even when a connection escalates its activities. A provisional connection that has not sent `server/activate` within 30 seconds is dropped. Clients MAY cap how many provisional connections they hold at once, rejecting further incoming connections as if they were lower priority.

A displaced connection receives [`client/goodbye`](messaging.md#client--server-clientgoodbye) reason `'another_server'` (or [`pair/abort`](pairing.md#client--server-pairabort) reason `concurrent_attempt` if it is a pairing handshake). A rejected incoming receives [`client/goodbye`](messaging.md#client--server-clientgoodbye) reason `'concurrent_attempt'` (or [`pair/abort`](pairing.md#client--server-pairabort) reason `concurrent_attempt` for pairings). The client then closes the connection.

### Client Initiated Connections

If clients prefer to initiate the connection instead of waiting for the server to connect, the server must be discoverable via mDNS using:
- Service type: `_sendspin-server._tcp.local.`
- Port: The port the Sendspin server is listening on (recommended: `8927`)
- TXT record: `path` key specifying the WebSocket endpoint, REQUIRED (recommended value: `/sendspin`)
- TXT record: `name` key specifying the friendly name of the server (optional)

Clients discover the server through mDNS and initiate a WebSocket connection using the advertised address and path.

The TXT `name` SHOULD match the `name` the server sends in [`server/hello`](messaging.md#server--client-serverhello). It is only a discovery-time hint; if the two differ, the `server/hello` value is authoritative.

**Note:** Do not advertise `_sendspin._tcp` if the client plans to initiate the connection.

#### Multiple servers (client-initiated)

Unlike server-initiated connections, servers cannot reclaim clients by reconnecting. How clients handle multiple discovered servers, server selection, and switching is implementation-defined.

**Note:** After this point, Sendspin works independently of how the connection was established. The Sendspin client is always the consumer of data like audio or metadata, regardless of who initiated the connection.

## Encryption

All Sendspin connections use end-to-end encryption based on the [Noise Protocol Framework](https://noiseprotocol.org/noise.html). Encryption is mandatory for all connections established through the standard discovery mechanisms described in [Establishing a Connection](#establishing-a-connection).

### Pattern

Sendspin uses the `KKpsk2` Noise pattern. Both static keys are pre-known to both parties (the `client_id` of the client and the `server_id` of the server are the static public keys), and a [Pre-Shared Key](#pre-shared-key) is mixed in at the end of the handshake's second message.

The **server is the Noise initiator**, the **client is the Noise responder**, regardless of which side initiated the WebSocket connection.

**Security properties.** Forward secrecy is provided by the ephemeral-key DH in each handshake: compromise of static keys or the PSK does not retroactively decrypt prior sessions' transport traffic (the exception is the first handshake message's `psk_id` payload, recoverable with the client's static key). Replay protection is provided by Noise's per-direction transport counter; a repeated or out-of-order ciphertext fails AEAD decryption and aborts the connection.

### Cipher Suites

A suite specifies the `<DH>_<cipher>_<hash>` part of the full Noise protocol name. Sendspin defines two:

- `25519_ChaChaPoly_SHA256` - software-friendly suite
- `25519_AESGCM_SHA256` - hardware-accelerated suite (AES-NI / ARMv8 Crypto Extensions)

Servers must support both suites. Clients must support at least one.

The client picks one suite and announces it in [`client/init`](messaging.md#client--server-clientinit); since servers are required to support every suite, no negotiation is needed.

### Identities

The `client_id` and `server_id` fields are the base64url-encoded (no padding) Curve25519 public keys of the client and server respectively, 43 characters each. These keys serve both as routing/persistence identifiers and as the static keys used in the Noise handshake.

**Key rotation.** Each side's static keypair is intended to be long-lived; the identifier is the pubkey, so rotating the keypair changes the identity. A server that rotates its static keypair (e.g., reprovisioned hardware, migrated host, lost private key) appears to clients as a different server. Operators who want to preserve identity across server moves must preserve the server's static private key (e.g., as part of the server's backup/restore set).

### Pre-Shared Key

The PSK is mixed into the handshake state at the end of the second handshake message (the `psk2` modifier). The transport-mode keys derived after the handshake therefore include the PSK, but the first handshake message's payload (sent by the server) is encrypted without the PSK mixed in.

To let the client select the right PSK before the PSK must be mixed in, the server includes a `psk_id` in the first handshake message's payload. The identifier is a 43-character base64url-encoded value (no padding) of a 32-byte SHA-256 output, derived deterministically from the PSK:

```
psk_id = base64url(SHA-256("sendspin-psk-id-v1" || PSK))
```

The label is the UTF-8 byte sequence of the literal characters shown (no NUL terminator, no surrounding quotes); `||` denotes byte concatenation. The same formula applies to all three PSK categories (long-term, pairing, Sentinel); the client stores each of its PSKs tagged with its category and, on match, the stored category determines how to proceed. The single handshake pattern (`KKpsk2`) is used in all three cases; only the PSK input differs.

The three PSK categories share one `psk_id` namespace, so a `psk_id` must be unique across them. Two categories sharing one would make a single wire `psk_id` map to two trust levels. Clients enforce this when records are configured (see [Management](management.md#records)).

The **Sentinel PSK** is a published constant used as the PSK input whenever no other PSK applies - i.e., before any pairing record exists. It provides no authentication on its own (its value is public); authentication, when needed, is established later during [Pairing](pairing.md#pairing). The sentinel value is:

```
Sentinel PSK = SHA-256("sendspin-sentinel-psk-v1")
             = 0x1b5e24dbc1aed95fc2a5a338a90c05df44bd10f5ec1f4cd66cbf86272767b9d3
```

and its `psk_id` is therefore also a published constant:

```
Sentinel psk_id = 0x185b15f6d2da4909bd1dc156a4ab206103abef0153bcd52d926170b95cf7ce8a
                = base64url "GFsV9tLaSQm9HcFWpKsgYQOr7wFTvNUtkmFwuVz3zoo"
```

The client decrypts the first handshake message's payload (possible without a PSK, as noted above), compares the included `psk_id` to the hash of each candidate PSK, and selects the one that matches. It then mixes that PSK in to process the second handshake message. If no candidate matches, the handshake fails. A PSK for a pairing method disabled in the client's [pairing config](management.md#server--client-managementset-pairing-config) is excluded from the candidate set, so a handshake referencing it fails as a lookup miss.

Two storage variants are supported for [long-term PSK](README.md#definitions) records, distinguished by whether the client also stores the server's `server_id`. The wire bytes and `psk_id` lookup are identical; only the post-match check differs.

- **Stored-pubkey model**: each long-term PSK is persisted alongside the server's `server_id`. After a `psk_id` match, the client verifies that the matched PSK's stored `server_id` equals the one in [`server/init`](messaging.md#server--client-serverinit); mismatch fails the handshake. Authentication relies on both the static keys and the PSK.
- **Shared-PSK model**: PSKs are persisted without an associated `server_id`; the `server_id` from [`server/init`](messaging.md#server--client-serverinit) is accepted at face value. Convenient for storage-constrained clients, but with weaker security properties - multiple servers may share the same PSK.

### Prologue

The prologue mixed into the Noise handshake state on both sides is the concatenation of the exact bytes of [`client/init`](messaging.md#client--server-clientinit) followed by the exact bytes of [`server/init`](messaging.md#server--client-serverinit), as transmitted on the wire (the JSON-encoded UTF-8 message body, without the WebSocket framing). This binds the cleartext init exchange to the handshake; tampering causes the handshake to fail.

Both sides MUST hash the raw message bytes exactly as sent and received, not a re-encoding of the parsed message.

### Failure Handling

Any handshake-phase failure - malformed cleartext message, unsupported `version`, unknown `suite`, handshake timeout, `psk_id` lookup miss, Noise AEAD failure, or AEAD failure once in transport mode - closes the WebSocket without sending any application-level error message. Implementations SHOULD apply a timeout (e.g., 30 seconds) for each side to receive the next expected message during the prologue and Noise-handshake phases.

### Re-handshake

The server may rerun the Noise handshake in transport mode to swap session keys without closing the WebSocket - typically to promote the trust level after a successful [pairing](pairing.md#pairing), to switch from Sentinel to a pairing PSK, or to rotate session keys on long-running connections.

The server initiates, as in the original handshake. The two [`noise/handshake`](messaging.md#client--server-noisehandshake) messages are sent as encrypted binary frames inside the current channel; `psk_id` in noise message 1 selects the PSK for the new session. `client/init` and `server/init` are not re-sent - `client_id`, `server_id`, and `suite` carry over. The new handshake's prologue is the prior handshake's hash `h`. No other messages flow during the exchange; once the new keys are in place, the connection continues with the usual [`server/hello`](messaging.md#server--client-serverhello) → [`client/hello`](messaging.md#client--server-clienthello) (the client re-asserts `trust_level`) → [`server/activate`](messaging.md#server--client-serveractivate).
