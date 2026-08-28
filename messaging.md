## Communication

Once the WebSocket connection is established, Client and Server perform an initial handshake before exchanging application data:

1. Client → Server: [`client/init`](#client--server-clientinit) (cleartext)
2. Server → Client: [`server/init`](#server--client-serverinit) (cleartext)
3. Server → Client: [`noise/handshake`](#client--server-noisehandshake) - Noise message 1 (cleartext)
4. Client → Server: [`noise/handshake`](#client--server-noisehandshake) - Noise message 2 (cleartext)
5. Both sides switch to Noise transport mode. From this point, all Sendspin application data is sent as WebSocket binary frames whose payloads are Noise transport ciphertexts.
6. Server → Client: [`server/hello`](#server--client-serverhello) (encrypted)
7. Client → Server: [`client/hello`](#client--server-clienthello) (encrypted)
8. Server → Client: [`server/activate`](#server--client-serveractivate) (encrypted)

No other messages should be sent before the initial [`server/activate`](#server--client-serveractivate) arrives. See [Encryption](connection.md#encryption) for cryptographic details.

Cleartext handshake messages (`client/init`, `server/init`, `noise/handshake`) are sent as WebSocket **text** frames containing JSON. After the encrypted channel is established, all messages are sent as WebSocket **binary** frames carrying Noise transport ciphertexts.

WebSocket control frames (Ping, Pong, Close; RFC 6455) are not Sendspin messages: they remain valid at any time, are not encrypted at the Noise layer, and Ping/Pong is the expected connection-liveness mechanism.

**Note:** In field definitions, `?` indicates an optional field (e.g., `field?`: type means the field may be omitted).

All messages have a `type` field identifying the message and a `payload` object containing message-specific data. The payload structure varies by message type and is detailed in each message section below.

**Message type prefixes.** The prefix before the `/` in a message `type` identifies a group of messages. `client/` and `server/` name the sender. `stream/` groups the messages that control a binary channel from the server to the client, and `client-stream/` those that control a binary channel from the client to the server; the two kinds of channel are independent and have separate lifetimes. `group/`, `management/`, `pair/`, and `noise/` name a subject. Only `client/`, `server/`, and `client-stream/` imply a direction; for every other prefix each message's definition gives it.

**Forward compatibility.** Clients and servers MUST ignore unrecognized `payload` fields (keys not defined for the message) rather than treating them as an error. Clients and servers MUST NOT send fields the specification does not define for the message, other than the `_`-prefixed [application-specific role](README.md#application-specific-roles) objects a message explicitly permits.

Message format example:

```json
{
  "type": "stream/start",
  "payload": {
    "server_transmitted": 1234567890,
    "player": {
      "codec": "opus",
      "sample_rate": 48000,
      "channels": 2,
      "bit_depth": 16
    },
    "artwork": {
      "channels": [
        {
          "source": "album",
          "format": "jpeg",
          "width": 800,
          "height": 800
        }
      ]
    }
  }
}
```

WebSocket binary messages are used to send JSON payloads, audio chunks, media art, and visualization data. Each binary message is a Noise transport ciphertext; after AEAD decryption, the first byte is a uint8 representing the message type. Throughout this specification, bit 0 refers to the least significant bit.

### Binary Message ID Structure

The first byte of every binary message is its message ID. IDs are assigned from the table below; each role's binary message definitions name the exact IDs it uses.

| IDs | Assignment |
|---|---|
| 0 | JSON message body (UTF-8) |
| 1 | [Fragmentation](#fragmentation) |
| 2-3 | Reserved for future use |
| 4-7 | Player role |
| 8-11 | Artwork role |
| 12-15 | Source role |
| 16-23 | Visualizer role |
| 24-191 | Reserved for future roles |
| 192-255 | Available for use by [application-specific roles](README.md#application-specific-roles) |

Future roles will be allocated aligned blocks of 4 or 8 IDs from the reserved 24-191 range.

**Note:** Role versions share the same binary message IDs (e.g., `player@v1` and `player@v2` both use IDs 4-7).

### Fragmentation

A single Noise transport message is limited to 65535 bytes by the Noise specification. Both defined cipher suites use a 16-byte AEAD authentication tag, and the message type byte occupies the first byte of the AEAD plaintext, so the application payload per frame is at most 65535 − 16 − 1 = 65518 bytes. Larger messages must be split across multiple WebSocket binary frames using the fragment message type.

**Wire format** (inside the AEAD-protected plaintext of each fragment frame):

- First fragment: `[1][flags][orig_type][data]`
- Subsequent fragments: `[1][flags][data]`

`flags` is a uint8. Bit 1 is set on the first fragment of a message and bit 0 on the last. Bits 2-7 are reserved and MUST be zero.

The concatenated `data` from all fragments yields the original message's payload (the bytes that would have followed the message type byte in a non-fragmented message of type `orig_type`).

**Constraints:**

- Only one fragmented message may be in flight at a time per direction. A sender must finish a fragmented message with a last fragment before sending any other frame in that direction, whether fragmented or not.
- Senders should not fragment messages that fit in a single non-fragmented frame.
- A sender MUST NOT use `1` as `orig_type`.

**Receiver behavior:** maintain a single reassembly buffer along with the in-flight `orig_type`. On a first fragment, read `orig_type` from byte 2 and start a new buffer with the rest of the frame; on any other fragment, append the frame's data to the buffer. When bit 0 is set, dispatch the buffer as a single message of type `orig_type` and clear it.

**Malformed sequences** are protocol errors; the receiver MUST close the connection. They are: a first fragment received while a fragmented message is in flight, a non-first fragment received with none in flight, a non-fragment frame received while a fragmented message is in flight, a nonzero reserved flag bit, and an `orig_type` of `1`.

## Clock Synchronization

Clients send `client/time` messages to maintain an accurate offset from the server's clock. Implementations MUST send these messages frequently enough to keep the filter convergent. The time-filter library's [Recommended Usage](https://github.com/Sendspin-Protocol/time-filter#recommended-usage) section describes a known-good burst-strategy baseline.

Binary audio messages contain timestamps in the server's time domain indicating when the audio should be played. Clients MUST use the [time-filter](https://github.com/Sendspin-Protocol/time-filter) algorithm to translate server timestamps to their local clock for synchronized playback. The time filter is a two-dimensional Kalman filter that tracks both clock offset and drift. See the [time-filter](https://github.com/Sendspin-Protocol/time-filter) repository for a C++ reference implementation and [aiosendspin](https://github.com/Sendspin-Protocol/aiosendspin/blob/main/aiosendspin/client/time_sync.py) for a Python implementation.

Each [`server/time`](#server--client-servertime) response provides the four timestamps needed by the filter: the client's transmitted timestamp, the server's received timestamp, the server's transmitted timestamp, and the client's receive time (captured locally when the response arrives). Clients feed these into the time filter via its `update` method and use its `compute_client_time` method to convert server timestamps to local clock values for playback scheduling.

A player MUST NOT report `available: true` until its time filter has converged enough to begin scheduling playback. A source MUST NOT report `available: true` until its time filter has converged enough to timestamp captured audio.

## Core messages
This section describes the fundamental messages that establish communication between clients and the server. These messages handle initial handshakes, ongoing clock synchronization, stream lifecycle management, and role-based state updates and commands.

Every client and server must implement all messages in this section regardless of their specific roles. Role-specific object details are documented in their respective role sections and need to be implemented only if the client supports that role.

[Management](management.md#management) messages are likewise required for all clients and servers. [Pairing](pairing.md#pairing) messages are required for all servers; clients implement the subset matching their advertised pairing methods.

### Client → Server: `client/init`

First message sent by the client after the WebSocket connection is established. Contains information necessary for conducting the Noise handshake.

- `client_id`: string - client's static public key (43-character base64url-encoded Curve25519, no padding). See [Identities](connection.md#identities). Persistent across reconnections so servers can associate clients with previous sessions (e.g., remembering group membership, settings, playback queue)
- `version`: integer (must be `1`) - version of the core message format that the client implements (independent of role versions)
- `suite`: '25519_ChaChaPoly_SHA256' | '25519_AESGCM_SHA256' - Noise cipher suite the client picked for this connection. See [Cipher Suites](connection.md#cipher-suites)

**Note:** `version` (here and in [`server/init`](#server--client-serverinit)) is an exact-match field naming the single core message format the sender speaks, not a minimum-supported version. Under this specification both sides send `1` and abort the handshake on any other value (see [Failure Handling](connection.md#failure-handling)); a future revision that changes the core format will bump the value and define its own negotiation semantics.

### Server → Client: `server/init`

Response to the [`client/init`](#client--server-clientinit) message with corresponding information about the server.

The server sends `server/init` immediately followed by the first [`noise/handshake`](#client--server-noisehandshake) message (Noise message 1) without waiting for any client message in between.

- `server_id`: string - server's static public key (43-character base64url-encoded Curve25519, no padding). See [Identities](connection.md#identities)
- `version`: integer (must be `1`) - version of the core message format that the server implements (independent of role versions)

### Client ↔ Server: `noise/handshake`

Carries one Noise handshake message. Sent twice during the handshake: once by the server (Noise message 1, sent immediately after [`server/init`](#server--client-serverinit)), and once by the client in response (Noise message 2).

- `data`: string - base64url-encoded Noise handshake message bytes (no padding)

The encrypted payload carried inside each Noise handshake message is a UTF-8 JSON object:

- **Noise message 1 payload** (server → client): 
  - `psk_id`: string - 43-character base64url-encoded SHA-256 hash derived from the PSK. Used by the client to select the PSK before processing message 2; the message-1 payload is decryptable without the PSK (see [Pre-Shared Key](connection.md#pre-shared-key)).
- **Noise message 2 payload** (client → server): the empty object as the literal two bytes `{}` (not a zero-length Noise payload)

A malformed inner handshake payload (not valid UTF-8 JSON of the shape above) is a handshake failure and closes the WebSocket (see [Failure Handling](connection.md#failure-handling)).

After both handshake messages have been exchanged, both sides switch to Noise transport mode (all subsequent messages travel as the binary Noise-ciphertext frames described above).

The same `noise/handshake` message is used for the in-band [re-handshake](connection.md#re-handshake): the two messages then travel as ordinary encrypted JSON messages (binary frames, message type `0`), not bare Noise bytes. Noise message 2 is still encrypted under the pre-re-handshake transport keys; the first frame each side sends after the handshake completes uses the new keys.

### Server → Client: `server/hello`

First message sent by the server after the Noise handshake completes. Sent as an encrypted message (binary frame, message type `0`). This message will be followed by a [`client/hello`](#client--server-clienthello) message from the client.

- `name`: string - friendly name of the server

### Client → Server: `client/hello`

Sent by the client once it has received [`server/hello`](#server--client-serverhello). Sent as an encrypted message (binary frame, message type `0`). Contains information about the client's capabilities and roles.

Players that can output audio should have the role `player`.

- `name`: string - friendly name of the client
- `device_info?`: object - optional information about the device
  - `product_name?`: string - device model/product name
  - `manufacturer?`: string - device manufacturer name
  - `software_version?`: string - software version of the client (not the Sendspin version)
  - `mac_address?`: string - MAC address of the network interface the connection is opened on, in lowercase colon-separated form (e.g., `aa:bb:cc:dd:ee:ff`)
- `trust_level`: 'user' | 'none' - the [trust level](README.md#definitions) the client extends to this server, governing which operations the server may issue. `'user'` reflects a pairing record for this server; `'none'` is sent in [pairing](pairing.md#pairing) handshakes and on [unpaired access](pairing.md#unpaired-access), where no record exists for this server
- `supported_roles`: string[] - versioned roles supported by the client (e.g., `player@v1`, `controller@v1`). Defined versioned roles are:
  - `player@v1` - outputs audio
  - `source@v1` - captures audio from a local input and streams it to the server
  - `controller@v1` - controls the current group
  - `metadata@v1` - displays text metadata describing the currently playing audio
  - `artwork@v1` - displays artwork images
  - `visualizer@v1` - visualizes audio
  - `color@v1` - receives colors derived from the current audio
- `player@v1_support?`: object - required if `player@v1` is listed, absent otherwise ([see player@v1 support object details](roles/player/v1.md#client--server-clienthello-playerv1-support-object))
- `source@v1_support?`: object - required if `source@v1` is listed, absent otherwise ([see source@v1 support object details](roles/source/v1.md#client--server-clienthello-sourcev1-support-object))
- `artwork@v1_support?`: object - required if `artwork@v1` is listed, absent otherwise ([see artwork@v1 support object details](roles/artwork/v1.md#client--server-clienthello-artworkv1-support-object))
- `visualizer@v1_support?`: object - required if `visualizer@v1` is listed, absent otherwise ([see visualizer@v1 support object details](roles/visualizer/v1.md#client--server-clienthello-visualizerv1-support-object))
- `supported_pair_methods`: object[] - pairing methods this client currently offers, each described by a [pair-method descriptor](pairing.md#client--server-clienthello-pair-method-descriptor). An implemented method that is [disabled](management.md#server--client-managementset-pairing-config) is omitted. Every client implements at least the Pairing PSK method (see [Pairing](pairing.md#pairing)).
- `unpaired_access`: object - whether this client currently admits [unpaired access](pairing.md#unpaired-access)
  - `enabled`: boolean

**Note:** Each role version may have its own support object (e.g., `player@v1_support`, `player@v2_support`). Application-specific roles or role versions follow the same pattern (e.g., `_myapp_display@v1_support`, `player@_experimental_support`).

A server MUST NOT activate a role version that was listed in `supported_roles` without its support object.

### Server → Client: `server/activate`

Declares the server's current purpose on this connection. Sent as an encrypted message (binary frame, message type `0`). May be re-sent any time to change the activity set.

Only after receiving the initial `server/activate` should the client send any other messages (including [`client/time`](#client--server-clienttime) and the initial [`client/state`](#client--server-clientstate) message).

- `activities`: ('playback' | 'pairing' | 'management')[] - the set of currently-active purposes on this connection. May be empty. Members are unordered and unique.
- `active_roles?`: string[] - versioned roles that are active for this client (e.g., `player@v1`, `controller@v1`). Required on the first `server/activate`; persists across subsequent `server/activate` messages that omit it. MUST be empty on connections not capable of playback (see below). A client treats a first `server/activate` that omits it as carrying an empty `active_roles`.
- `pairing?`: object - parameters of the pairing attempt this activation admits. Required when `'pairing'` is in `activities`; absent otherwise. A client ignores this field when `activities` does not include `'pairing'`.
  - `method`: 'dynamic_pairing_code' | 'pairing_psk' | 'static_pairing_code' - pairing method the server picked, drawn from the client's `supported_pair_methods`.
  - `format?`: 'digits' | 'qr_code' - the dynamic [emission format](pairing.md#dynamic-pairing-code-flow), drawn from the client's `dynamic_pairing_code` descriptor. Required when `method` is `'dynamic_pairing_code'`; absent otherwise. The server selects `qr_code` only when its operator interface can scan a QR code.
  - `languages?`: string[] - non-empty list of [BCP 47](https://www.rfc-editor.org/rfc/rfc5646) language tags in descending operator preference (e.g. `["ca", "es", "en"]`), for spoken [pairing code emission](pairing.md#dynamic-pairing-code-flow). Optional when `method` is `'dynamic_pairing_code'` with the `digits` emission format; absent otherwise.

The activity sets the server may legitimately declare are constrained by which PSK matched during the [Noise handshake](connection.md#encryption):

| PSK matched | Allowed activity sets |
|---|---|
| [long-term PSK](README.md#definitions) | `['pairing']` or any subset of `{'playback', 'management'}` |
| [pairing PSK](README.md#definitions) | `['pairing']` |
| [Sentinel PSK](connection.md#pre-shared-key) | `[]`, `['pairing']`, `['playback']`¹ |

¹ `['playback']` on the Sentinel PSK is only allowed when the client has [unpaired access](pairing.md#unpaired-access) enabled.

`pairing.method` MUST be `'pairing_psk'` if and only if the matched PSK is the [pairing PSK](README.md#definitions). It MUST also be a method the client listed in [`supported_pair_methods`](#client--server-clienthello).

**Playback-capable connections.** A connection is *playback-capable* when its `activities` extended with `'playback'` are an allowed set for the matched PSK; a connection already declaring `'playback'` is therefore playback-capable exactly when its `activities` are an allowed set. Only a playback-capable connection MAY carry a non-empty `active_roles`, and it may do so even when `'playback'` is not currently in `activities`. The client re-evaluates this constraint on every `server/activate` against the persisted `active_roles`: if a later activation changes `activities` so the connection is no longer playback-capable without explicitly sending `active_roles`, the persisted roles are treated as empty rather than the message rejected.

`server/activate` is *admissible* when it satisfies the constraints above. When one is not admissible, the client rejects it, selecting the response by the first rule that applies:

- If the matched PSK is the [Sentinel PSK](connection.md#pre-shared-key), the client does not have [unpaired access](pairing.md#unpaired-access) enabled, and enabling unpaired access would make the activation admissible - close the connection with [`client/goodbye`](#client--server-clientgoodbye) reason `'pairing_required'`.
- If `activities` is not an allowed set for the matched PSK, or `active_roles` is non-empty on a connection that is not playback-capable - close the connection with [`client/goodbye`](#client--server-clientgoodbye) reason `'unauthorized'`.
- If `'pairing'` is in `activities` with a `pairing.method` the matched PSK disallows or the client does not currently offer, or a `pairing.format` the client does not currently offer - reply with [`pair/abort`](pairing.md#client--server-pairabort) reason `method_not_supported`, leaving the connection open. The check uses the live pairing configuration, which may have drifted from [`supported_pair_methods`](#client--server-clienthello); the server may re-activate, or [re-handshake](connection.md#re-handshake) for a fresh advertisement.

**Worked example (`pairing_required` vs `unauthorized`).** A Sentinel-keyed connection to a client with unpaired access disabled receives `activities: ['playback']` and `active_roles: ['player@v1']`. Under a hypothetical `unpaired_access: enabled`, `['playback']` would be an allowed set for the Sentinel PSK and the connection would be playback-capable, so the activation would be admissible: the client closes with `'pairing_required'`. If the same connection instead received `activities: ['playback', 'management']`, no unpaired-access setting makes that set allowed on the Sentinel PSK, so the reason is `'unauthorized'`.

Servers SHOULD declare the minimal set of activities that reflects the connection's current purpose, and drop an activity as soon as that purpose ends. Admission between competing connections is decided by the highest-ranked declared activity (see [Multiple servers](connection.md#multiple-servers-server-initiated)), so keeping an unused activity declared would degrade multi-server cooperation.

Servers normally activate the client's [preferred](README.md#priority-and-activation) version of each role, but MAY omit a role at their discretion (e.g., based on trust level, deployment context, or operator policy). Checking `active_roles` is therefore required to determine what the client may actually use on this session.

When a `server/activate` removes a role from `active_roles`, the server MUST first end that role's output by sending [`stream/end`](#server--client-streamend) for stream roles (`player`, `artwork`, `visualizer`), or a [`server/state`](#server--client-serverstate) with a null role object for state roles (`metadata`, `color`, `controller`) - so the client never holds live data for an inactive role.

### Client → Server: `client/time`

Sends current internal clock timestamp (in microseconds) to the server.
Once received, the server responds with a [`server/time`](#server--client-servertime) message containing timing information to establish clock offsets.

- `client_transmitted`: integer - client's internal clock timestamp in microseconds

### Server → Client: `server/time`

Response to the [`client/time`](#client--server-clienttime) message with timestamps to establish clock offsets.

For synchronization, all timing is relative to the server's monotonic clock. These timestamps have microsecond precision and are not necessarily based on epoch time.

- `client_transmitted`: integer - client's internal clock timestamp received in the `client/time` message
- `server_received`: integer - timestamp that the server received the `client/time` message in microseconds
- `server_transmitted`: integer - timestamp that the server transmitted this message in microseconds

### Client → Server: `client/state`

Client sends state updates to the server. Contains client-level state and role-specific state objects.

Sent once the client is ready to report its operational status (`available`), and whenever any state changes thereafter. A player reports `available: true` only after it has established [clock synchronization](#clock-synchronization). The server MUST NOT send binary data to a client before that client has sent its initial `client/state`. When a role becomes active in `active_roles`, send an update that includes that role's object.

A client whose `active_roles` are non-empty sends the initial `client/state` even when none of its roles defines a state object.

Every message MUST carry `available` and the full state of each role object it includes. Omitting a role object leaves that role's state unchanged.

- `available`: boolean - whether the client is available to participate in Sendspin playback
  - `true` - client is operational and ready to participate in playback; for a player or source this means its clock is synchronized with the server.
  - `false` - client's output is in use by an external system and is not currently participating in Sendspin playback with this server. See [External Source Handling](#external-source-handling)
- `player?`: object - only if client has `player` role ([see player state object details](roles/player/v1.md#client--server-clientstate-player-object))
- `source?`: object - only if client has `source` role ([see source state object details](roles/source/v1.md#client--server-clientstate-source-object))

[Application-specific roles](README.md#application-specific-roles) may also include objects in this message (keys starting with `_`).

### External Source Handling

A client's output can be taken over by a non-Sendspin activity (playing other media, another protocol, an HDMI input, and so on). How it reports this depends on whether it will still yield its output back to Sendspin on request.

#### Interruptible activity (client stays available)

If the external activity can be interrupted by Sendspin playback at any time, the client SHOULD remain `available: true` so the server can take it over.

To stop rendering its group's audio while performing non-Sendspin activity, a client MAY leave its current group by sending a `client/state` with `available: false` immediately followed by a `client/state` with `available: true` (the server behavior below then moves it to a solo group and does not rejoin it). This is only needed while the group's `playback_state` is `'playing'`.

#### Non-interruptible activity (client becomes unavailable)

When a client reports `available: false`, it indicates the client's output is in use by an external system (e.g., a different audio source, HDMI input, or local media playback) and will not participate in Sendspin playback with this server until it returns to `available: true`.

A client SHOULD report `available: false` only while it will not yield its output to Sendspin, and SHOULD return to `available: true` as soon as it is again willing to be taken over.

#### Server behavior when a client becomes unavailable (`available: false`):

If the client is in a multi-client group:
1. Remember the client's current group as its "previous group" (see [switch command cycle](roles/controller/v1.md#switch-command-cycle))
2. Move the client to a new solo group (stopped)
   - Send [`group/update`](#server--client-groupupdate) with the new group information
   - Send [`stream/end`](#server--client-streamend) for all active streams

If the client is already in a solo group:
- Stop playback and send [`stream/end`](#server--client-streamend) for all active streams
- If `playback_state` was not already `'stopped'`, send [`group/update`](#server--client-groupupdate) reporting `playback_state: 'stopped'`

When a client returns to `available: true`, the server MUST NOT auto-rejoin it to its previous group or restart playback; the client remains in the solo group and rejoins only via an explicit [`switch`](roles/controller/v1.md#switch-command-cycle).

### Client → Server: `client/command`

Client sends commands to the server. Contains command objects based on the client's supported roles.

- `controller?`: object - only if client has `controller` role ([see controller command object details](roles/controller/v1.md#client--server-clientcommand-controller-object))

[Application-specific roles](README.md#application-specific-roles) may also include objects in this message (keys starting with `_`).

### Server → Client: `server/state`

Server sends state updates to the client. Contains role-specific state objects.

Every message MUST carry the full state of each role object it includes. Omitting a role object leaves that role's state unchanged.

A role object set to `null` clears all of that role's state.

- `metadata?`: object | null - only sent to clients with `metadata` role ([see metadata state object details](roles/metadata/v1.md#server--client-serverstate-metadata-object))
- `controller?`: object | null - only sent to clients with `controller` role ([see controller state object details](roles/controller/v1.md#server--client-serverstate-controller-object))
- `color?`: object | null - only sent to clients with `color` role ([see color state object details](roles/color/v1.md#server--client-serverstate-color-object))

[Application-specific roles](README.md#application-specific-roles) may also include objects in this message (keys starting with `_`).

### Server → Client: `server/command`

Server sends commands to the client. Contains role-specific command objects.

- `player?`: object - only sent to clients with `player` role ([see player command object details](roles/player/v1.md#server--client-servercommand-player-object))
- `source?`: object - only sent to clients with `source` role ([see source command object details](roles/source/v1.md#server--client-servercommand-source-object))

[Application-specific roles](README.md#application-specific-roles) may also include objects in this message (keys starting with `_`).

### Server → Client: `stream/start`

Starts a stream for one or more roles. If sent for a role that already has an active stream, updates the stream configuration without clearing buffers. If a parameter change requires rebuffering (e.g., a sample rate change), the receiver handles this internally: it does not clear buffers unless its implementation requires it, and may document its specific behavior.

- `server_transmitted`: integer - timestamp that the server transmitted this message in microseconds
- `player?`: object - only sent to clients with the `player` role ([see player object details](roles/player/v1.md#server--client-streamstart-player-object))
- `artwork?`: object - only sent to clients with the `artwork` role ([see artwork object details](roles/artwork/v1.md#server--client-streamstart-artwork-object))
- `visualizer?`: object - only sent to clients with the `visualizer` role ([see visualizer object details](roles/visualizer/v1.md#server--client-streamstart-visualizer-object))

[Application-specific roles](README.md#application-specific-roles) may also include objects in this message (keys starting with `_`).

The server MUST NOT send `stream/start` to a client that is not [`available`](#client--server-clientstate) (e.g. a client whose output is taken by an [external source](#external-source-handling)).

### Server → Client: `stream/clear`

Instructs clients to clear buffers without ending the stream. Used for seek operations and track jumps (switching to a different track without stopping the stream).

- `server_transmitted`: integer - timestamp that the server transmitted this message in microseconds
- `roles?`: string[] - which roles to clear: '[player](roles/player/v1.md#server--client-streamclear-player)', '[visualizer](roles/visualizer/v1.md#server--client-streamclear-visualizer)', or both. If omitted, clears both roles

[Application-specific roles](README.md#application-specific-roles) may also be included in this array (names starting with `_`).

### Client → Server: `stream/request-format`

Request different stream format (upgrade or downgrade). Available for clients with the `player`, `artwork`, or `visualizer` role.

- `player?`: object - only for clients with the `player` role ([see player object details](roles/player/v1.md#client--server-streamrequest-format-player-object))
- `artwork?`: object - only for clients with the `artwork` role ([see artwork object details](roles/artwork/v1.md#client--server-streamrequest-format-artwork-object))
- `visualizer?`: object - only for clients with the `visualizer` role ([see visualizer object details](roles/visualizer/v1.md#client--server-streamrequest-format-visualizer-object))

[Application-specific roles](README.md#application-specific-roles) may also include objects in this message (keys starting with `_`).

Response when a stream is active for the role: [`stream/start`](#server--client-streamstart) with the new configuration. If the server cannot honor the request, the stream continues in a configuration the client supports, and the server MUST NOT treat the request as an error.

Response when no stream is active for the role: the server MUST NOT start a stream in response, but SHOULD remember the requested format to apply to the next stream it starts for that role.

**Note:** Clients can use this message to adapt to changing network conditions, CPU constraints, or display requirements. The server maintains separate encoding for each client, allowing heterogeneous device capabilities within the same group.

### Server → Client: `stream/end`

Ends the stream for one or more roles. When received, clients should stop output and clear buffers for the specified roles. This message is expected to be sent when playback is over and the queue is empty. Specifically:

- **Track transitions** (a track ends and the next begins naturally): no stream commands should be sent. The stream continues uninterrupted to support gapless playback and server-inserted crossfade.
- **Seeks** (jumping to a position within the current track): send `stream/clear` instead.
- **Track jumps** (skipping to a different track): treat identically to a seek, sending `stream/clear` instead of `stream/end`. Conceptually, the entire queue is a single continuous stream.

Sending `stream/end` in these cases is explicitly prohibited because it signals actual playback termination, causing clients to stop output entirely rather than continue playing.

- `server_transmitted`: integer - timestamp that the server transmitted this message in microseconds
- `roles?`: string[] - roles to end streams for ('player', 'artwork', 'visualizer'). If omitted, ends all active streams

[Application-specific roles](README.md#application-specific-roles) may also be included in this array (names starting with `_`).

### Server → Client: `group/update`

State update of the group this client is part of.

Every message MUST carry the full group state.

- `playback_state`: 'playing' | 'stopped' - playback state of the group
- `group_id`: string - group identifier
- `group_name`: string - friendly name of the group

### Server → Client: `server/unpair`

Sent by a paired server to drop its own pairing record from the client. Valid at any time regardless of the current `activities`; does not require `'management'` in the activity set. No payload fields.

Client behavior:

- Remove the matched pairing record, send [`client/goodbye`](#client--server-clientgoodbye) reason `'unpaired'`, and close the connection.
- If the matched record is a **shared-PSK record** (not bound to a `server_id`; may back other servers - see [Records](management.md#records)), the client MUST NOT remove it. It still sends `client/goodbye` reason `'unpaired'` and closes. Wholesale removal of a shared record requires [`management/remove-record`](management.md#server--client-managementremove-record).
- If the connection's `trust_level` is `'none'` (e.g., an in-flight pairing handshake), ignore the message and continue unchanged.

### Client → Server: `client/goodbye`

Sent by the client before gracefully closing the connection. This allows the client to inform the server why it is disconnecting.

Upon receiving this message, the server should initiate the disconnect.

- `reason`: 'another_server' | 'shutdown' | 'restart' | 'user_request' | 'unauthorized' | 'pairing_required' | 'concurrent_attempt' | 'unpaired'
  - `another_server` - client is switching to a different server. A client that leaves one server for another MUST send this reason to the server it is leaving. Server SHOULD NOT auto-reconnect but SHOULD show the client as available for future playback
  - `shutdown` - client is shutting down. When the device is powering off or otherwise not coming back and no more specific reason applies, clients SHOULD send this reason. Server should not auto-reconnect
  - `restart` - client is restarting and will reconnect. Server should auto-reconnect
  - `user_request` - user explicitly requested to disconnect from this server. Server should not auto-reconnect
  - `unauthorized` - the client is no longer authorized for the connection: either the server declared an activity set the client is not authorized for (e.g., `'management'` without `'user'` [trust level](README.md#definitions)), or the client removed its own pairing record (see [`management/remove-record`](management.md#server--client-managementremove-record)) and can no longer authenticate. Server should not auto-reconnect with the same activity set
  - `pairing_required` - the client refused an [unpaired access](pairing.md#unpaired-access) connection because it does not have unpaired access enabled. Server should not auto-reconnect without pairing first
  - `concurrent_attempt` - the client refused the connection because a higher-or-equal-priority connection is already active (e.g., one with `'management'` in its activity set, or a pairing handshake when the incoming connection is also pairing). Server may retry later
  - `unpaired` - the client has processed [`server/unpair`](#server--client-serverunpair) from this server. Server should not auto-reconnect

**Note:** On a client-initiated connection the server cannot reconnect; the reconnect guidance then applies to the client re-establishing the connection.

Clients may close the connection without sending this message (e.g., crash, network loss), or immediately after sending `client/goodbye` without waiting for the server to disconnect. When a client disconnects without sending `client/goodbye`:

- On a connection whose `activities` are empty, or include `'playback'`, servers should assume the disconnect reason is `restart` and attempt to auto-reconnect.
- Otherwise, servers should treat the drop as a session termination and not auto-reconnect; resumption, if desired, is operator-driven.
- Servers should also apply backoff on repeated Noise-handshake failures to avoid tight reconnect loops. After repeated consecutive failures, the server SHOULD stop auto-reconnecting until there is reason to expect success (e.g., the client re-announces via mDNS or network conditions change).
