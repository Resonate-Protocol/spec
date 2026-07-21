## Communication

Once the WebSocket connection is established, Client and Server perform an initial handshake before exchanging application data:

1. Client → Server: [`client/init`](#client--server-clientinit) (cleartext)
2. Server → Client: [`server/init`](#server--client-serverinit) (cleartext)
3. Server → Client: [`noise/handshake`](#client--server-noisehandshake) - Noise message 1 (cleartext)
4. Client → Server: [`noise/handshake`](#client--server-noisehandshake) - Noise message 2 (cleartext)
5. Both sides switch to Noise transport mode. From this point, all WebSocket frames are binary, and all payloads are Noise transport ciphertexts.
6. Server → Client: [`server/hello`](#server--client-serverhello) (encrypted)
7. Client → Server: [`client/hello`](#client--server-clienthello) (encrypted)
8. Server → Client: [`server/activate`](#server--client-serveractivate) (encrypted)

No other messages should be sent before the initial [`server/activate`](#server--client-serveractivate) arrives. See [Encryption](connection.md#encryption) for cryptographic details.

Cleartext handshake messages (`client/init`, `server/init`, `noise/handshake`) are sent as WebSocket **text** frames containing JSON. After the encrypted channel is established, all messages are sent as WebSocket **binary** frames carrying Noise transport ciphertexts.

**Note:** In field definitions, `?` indicates an optional field (e.g., `field?`: type means the field may be omitted).

All messages have a `type` field identifying the message and a `payload` object containing message-specific data. The payload structure varies by message type and is detailed in each message section below.

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

Binary message IDs typically use **bits 7-2** for role type and **bits 1-0** for message slot, allocating 4 IDs per role. Roles with expanded allocations use **bits 2-0** for message slot (8 IDs).

**Role assignments:**
- `00000000` (0): JSON message body (UTF-8)
- `00000001` (1): Reserved for future use
- `0000001x` (2-3): Used for [Fragmentation](#fragmentation)
- `000001xx` (4-7): Player role
- `000010xx` (8-11): Artwork role
- `000011xx` (12-15): Source role
- `00010xxx` (16-23): Visualizer role
- Roles 6-47 (IDs 24-191): Reserved for future roles
- Roles 48-63 (IDs 192-255): Available for use by [application-specific roles](README.md#application-specific-roles)

**Message slots:**
- Slot 0: `xxxxxx00`
- Slot 1: `xxxxxx01`
- Slot 2: `xxxxxx10`
- Slot 3: `xxxxxx11`

Roles with expanded allocations have slots 0-7.

**Note:** Role versions share the same binary message IDs (e.g., `player@v1` and `player@v2` both use IDs 4-7).

### Fragmentation

A single Noise transport message is limited to 65535 bytes by the Noise specification. Both defined cipher suites use a 16-byte AEAD authentication tag, and the message type byte occupies the first byte of the AEAD plaintext, so the application payload per frame is at most 65535 − 16 − 1 = 65518 bytes. Larger messages must be split across multiple WebSocket binary frames using the fragment message types.

**Wire format** (inside the AEAD-protected plaintext of each fragment frame):

A fragmented message consists of an opening fragment-more frame (carrying `orig_type`), zero or more continuation fragment-more frames, and a closing fragment-end frame. The minimum is one fragment-more frame followed by one fragment-end frame.

Bit 0 is the last-fragment flag: `00000010` (2) is a fragment-more frame, `00000011` (3) is a fragment-end frame.

- Fragment-more (type `2`):
  - First fragment of a fragmented message: `[2][orig_type][data]`
  - Subsequent non-final fragments: `[2][data]`
- Fragment-end (type `3`): `[3][data]`

The format of a type `2` frame depends on the receiver's state: when no fragmented message is in flight, a type `2` frame begins a new one and carries `orig_type`; when a fragmented message is already in flight, a type `2` frame is a continuation and carries only `data`.

The concatenated `data` from all fragments yields the original message's payload (the bytes that would have followed the message type byte in a non-fragmented message of type `orig_type`).

**Constraints:**

- Only one message may be in flight at a time across the entire connection. If a message is fragmented, the sender must finish sending it (with a fragment-end frame) before starting another.
- Senders should not fragment messages that fit in a single non-fragmented frame.

**Receiver behavior:** maintain a single reassembly buffer along with the in-flight `orig_type`. On a fragment-more frame when no message is in flight, read `orig_type` from byte 1, then start a new buffer with the rest of the frame. On a fragment-more frame when a message is in flight, append the frame's data to the buffer. On a fragment-end frame, append the frame's data and dispatch the result as a single message of type `orig_type`, then clear the buffer.

## Clock Synchronization

Clients send `client/time` messages to maintain an accurate offset from the server's clock. Implementations MUST send these messages frequently enough to keep the filter convergent. See the time-filter library's [Recommended Usage](https://github.com/Sendspin-Protocol/time-filter#recommended-usage) section for a known-good burst-strategy baseline.

Binary audio messages contain timestamps in the server's time domain indicating when the audio should be played. Clients MUST use the [time-filter](https://github.com/Sendspin-Protocol/time-filter) algorithm to translate server timestamps to their local clock for synchronized playback. The time filter is a two-dimensional Kalman filter that tracks both clock offset and drift. See the [time-filter](https://github.com/Sendspin-Protocol/time-filter) repository for a C++ reference implementation and [aiosendspin](https://github.com/Sendspin-Protocol/aiosendspin/blob/main/aiosendspin/client/time_sync.py) for a Python implementation.

Each [`server/time`](#server--client-servertime) response provides the four timestamps needed by the filter: the client's transmitted timestamp, the server's received timestamp, the server's transmitted timestamp, and the client's receive time (captured locally when the response arrives). Clients feed these into the time filter via its `update` method and use its `compute_client_time` method to convert server timestamps to local clock values for playback scheduling.

A player MUST NOT report `available: true` until its time filter has converged enough to begin scheduling playback. A source MUST NOT report `available: true` until its time filter has converged enough to timestamp captured audio.

## Playback Synchronization

This section defines rules that require all implementations to provide a good experience, keeping playback seamlessly synchronized between speakers. While implementations can choose their own strategy, this section describes the minimal requirements that must be met by players. For a recommended strategy that is compliant, see the [Suggested correction strategy](#suggested-correction-strategy) subsection below.

### Correction Quality

- **Inaudible corrections:** In steady state, individual corrections MUST NOT produce audible noise, warble, or distortion during normal listening.
- **Maximum speed deviation:** The effective playback speed MUST stay within ±0.5% of normal speed, measured as a sliding average over 150 ms. This bounds continuous (steady-state) correction. A discrete one-shot resynchronization after a disturbance (startup, buffer underrun, or an error too large to correct smoothly) is not a speed deviation and is exempt; such events MUST be rare.

### Sync Accuracy

Sync accuracy is measured at the audio output, against what the time-filter predicts the local time should be (not against the true server clock). Use of the [time-filter](#clock-synchronization) is required to meet these minimum standards. The error is the absolute difference between when a sample actually plays in the client's local clock and the local time the time-filter predicts for that sample's server timestamp.

Each client is responsible for maintaining its own synchronization with the server's timestamps.

- **Accuracy floor:** In steady state, implementations MUST keep this error within ±1 ms. The only exception is the one-shot resynchronization exempted from the speed cap above, which MUST be rare.
- **Accuracy target:** Implementations SHOULD aim for ±0.5 ms.
- Clients subtract their [`static_delay_ms`](#client--server-clientstate-player-object) from server timestamps before scheduling playback.
- Audio chunks may arrive with timestamps in the past due to network delays or buffering; clients should drop these late chunks to maintain sync.

### Startup Behavior

- **No startup warble:** During startup, the client MUST NOT produce audible pitch modulation, warble, or other transient artifacts in the audio output.

### Server Audio Send Constraints

- **Chunk duration bounds:** A server MUST NOT send an audio chunk longer than 150 ms, and SHOULD NOT send one shorter than 15 ms (the final chunk of a stream or the chunk before a format change MAY be shorter).
- The server sends audio to late-joining clients with future timestamps only, allowing them to buffer and start playback in sync with existing clients.
- After sending [`stream/start`](#server--client-streamstart) or [`stream/clear`](#server--client-streamclear) messages, servers must schedule the first audio timestamp far enough in the future to satisfy each player's lead (see [Server behavior](#client--server-clienthello-playerv1-support-object)). For live streams the buffer cannot grow after playback begins, so the lead must already be reached before the first chunk plays.
- Servers factor in each client's [`static_delay_ms`](#client--server-clientstate-player-object) when calculating how far ahead to send audio, keeping effective buffer headroom constant.

### Suggested correction strategy

This is one valid correction strategy for clients with the `player` role: discrete sample deletion and insertion. It is an example, not a requirement. New implementers can use it as a starting point, especially where CPU or memory is limited: it needs no interpolation and leaves the audio bit-exact except at the moments it corrects.

Other strategies are allowed and encouraged as long as they meet the rules in this section. For example, asynchronous sample-rate conversion (ASRC) continuously resamples the stream to track the clock, trading CPU/DSP load for lower steady-state distortion than discrete frame drops.

#### Sample deletion and insertion

The player renders decoded frames at their server timestamps translated to local time by the time-filter, and corrects accumulated drift by occasionally deleting or duplicating whole frames. At realistic clock drift these corrections are small and infrequent (a few per second) and individually inaudible. A "frame" is one sample across all channels (e.g. one stereo pair).

**Soft correction.** Per decoded chunk:

1. Measure the time error between when the chunk is scheduled to play (its server timestamp via the time-filter) and where the renderer will reach it in the output buffer.
2. If the absolute error is below the dead band (~100 µs), output the chunk unchanged.
3. Otherwise correct by `N` frames: if playback is running late (the chunk reaches the output after its scheduled local time), drop `N` frames to catch up; if running early, duplicate `N` frames to wait. Residual error beyond the step carries to the next chunk.

**Choosing N.** Use the smallest `N` that keeps up with drift, scaled to hold the step duration constant across sample rates: `N = round(21 µs × sample_rate_hz / 1,000,000)` (N=1 at 44.1 and 48 kHz, 2 at 96 kHz, 4 at 192 kHz). A chunk's correction MUST NOT exceed the ±0.5% speed cap, so `N ≤ floor(0.005 × samples_in_chunk)`. Keep `N` small; at realistic drift any `N` in this range stays masked.

**Drop** removes the `N` frames and lets the neighbouring frames abut. **Duplicate** repeats a boundary frame `N` times. The output is the original samples with `N` removed or `N` repeated, bit-exact everywhere else.

**Large errors and startup.** When the error would otherwise exceed the ±1 ms floor, or on startup, [`stream/start`](#server--client-streamstart), [`stream/clear`](#server--client-streamclear), or recovery from underrun, snap to the correct position in one shot instead of soft-correcting: if playback is late, drop a leading prefix equal to the excess; if early, insert silence of the equivalent duration. This is a deliberate discontinuity and MUST be rare.

```mermaid
sequenceDiagram
    participant Client
    participant Server

    Note over Client,Server: Noise handshake complete (see Communication)

    Server->>Client: server/hello (name)
    Client->>Server: client/hello (roles and capabilities)
    Server->>Client: server/activate (activities, active_roles)

    loop Continuous clock sync
        Client->>Server: client/time (client clock)
        Server->>Client: server/time (timing + offset info)
    end

    Note over Client,Server: Clock synchronization established
    Client->>Server: client/state (available: true, player: volume, muted)

    alt Stream starts
        Server->>Client: stream/start (codec, format details)
    end

    Server->>Client: group/update (playback_state, group_id, group_name)
    Server->>Client: server/state (metadata, controller, color)

    loop During playback
        alt Player role
            Server->>Client: binary Type 4 (audio chunks with timestamps)
        end
        alt Artwork role
            Server->>Client: binary Types 8-11 (artwork channels 0-3)
        end
        alt Visualizer role
            Server->>Client: binary Types 16-20 (loudness, beat, f_peak, spectrum, peak)
        end
    end

    alt Player requests format change
        Client->>Server: stream/request-format (codec, sample_rate, etc)
        Server->>Client: stream/start (player: new format)
    end

    alt Seek operation
        Server->>Client: stream/clear (roles: [player, visualizer])
    end

    alt Track jump (skip to different track)
        Server->>Client: stream/clear (roles: [player, visualizer])
    end

    alt Controller role
        Client->>Server: client/command (controller: play/pause/seek/volume/switch/etc)
    end

    alt State changes
        Client->>Server: client/state (state and/or player changes)
    end

    alt Server commands player
        Server->>Client: server/command (player: volume, mute)
    end

    Server->>Client: stream/end (ends all role streams)

    alt Graceful disconnect
        Client->>Server: client/goodbye (reason)
        Note over Client,Server: Server initiates disconnect
    end
```

## Core messages
This section describes the fundamental messages that establish communication between clients and the server. These messages handle initial handshakes, ongoing clock synchronization, stream lifecycle management, and role-based state updates and commands.

Every Sendspin client and server must implement all messages in this section regardless of their specific roles. Role-specific object details are documented in their respective role sections and need to be implemented only if the client supports that role.

[Management](management.md#management) messages are likewise required for all clients and servers. [Pairing](pairing.md#pairing) messages are required for all servers; clients implement the subset matching their advertised pairing methods.

### Client → Server: `client/init`

First message sent by the client after the WebSocket connection is established. Contains information necessary for conducting the Noise handshake.

- `client_id`: string - client's static public key (43-character base64url-encoded Curve25519, no padding). See [Identities](connection.md#identities). Persistent across reconnections so servers can associate clients with previous sessions (e.g., remembering group membership, settings, playback queue)
- `version`: integer (must be `1`) - version of the core message format that the Sendspin client implements (independent of role versions)
- `suite`: string - Noise cipher suite the client picked for this connection. See [Cipher Suites](connection.md#cipher-suites)

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
  - `psk_id`: string - 43-character base64url-encoded SHA-256 hash derived from the PSK. Used by the client to select the PSK before processing message 2. See [Pre-Shared Key](connection.md#pre-shared-key).
- **Noise message 2 payload** (client → server): empty object `{}`

After both handshake messages have been exchanged, both sides switch to Noise transport mode. All subsequent WebSocket frames are binary, and all payloads are Noise transport ciphertexts.

The same `noise/handshake` message is used for the in-band [re-handshake](connection.md#re-handshake): the two messages then travel as binary frames encrypted under the current transport keys rather than as cleartext text frames.

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
  - `controller@v1` - controls the current Sendspin group
  - `metadata@v1` - displays text metadata describing the currently playing audio
  - `artwork@v1` - displays artwork images
  - `visualizer@v1` - visualizes audio
  - `color@v1` - receives colors derived from the current audio
- `player@v1_support?`: object - only if `player@v1` is listed ([see player@v1 support object details](roles/player/v1.md#client--server-clienthello-playerv1-support-object))
- `source@v1_support?`: object - only if `source@v1` is listed ([see source@v1 support object details](roles/source/v1.md#client--server-clienthello-sourcev1-support-object))
- `artwork@v1_support?`: object - only if `artwork@v1` is listed ([see artwork@v1 support object details](roles/artwork/v1.md#client--server-clienthello-artworkv1-support-object))
- `visualizer@v1_support?`: object - only if `visualizer@v1` is listed ([see visualizer@v1 support object details](roles/visualizer/v1.md#client--server-clienthello-visualizerv1-support-object))
- `supported_pair_methods?`: object[] - pairing methods this client offers, each described by a [pair-method descriptor](pairing.md#client--server-clienthello-pair-method-descriptor).
- `unpaired_access`: object - whether this client currently admits [unpaired access](pairing.md#unpaired-access)
  - `enabled`: boolean

**Note:** Each role version may have its own support object (e.g., `player@v1_support`, `player@v2_support`). Application-specific roles or role versions follow the same pattern (e.g., `_myapp_display@v1_support`, `player@_experimental_support`).

### Server → Client: `server/activate`

Declares the server's current purpose on this connection. Sent as an encrypted message (binary frame, message type `0`). May be re-sent any time to change the activity set.

Only after receiving the initial `server/activate` should the client send any other messages (including [`client/time`](#client--server-clienttime) and the initial [`client/state`](#client--server-clientstate) message if the client has roles that require state updates).

- `activities`: ('playback' | 'pairing' | 'management')[] - the set of currently-active purposes on this connection. May be empty. Members are unordered and unique.
- `active_roles?`: string[] - versioned roles that are active for this client (e.g., `player@v1`, `controller@v1`). Required on the first `server/activate`; persists across subsequent `server/activate` messages that omit it. MUST be empty on connections not capable of playback (see below).
- `selected_pair_method?`: 'dynamic_pin' | 'pairing_psk' | 'static_pin' - pairing method the server picked, drawn from the client's `supported_pair_methods`. Required when `'pairing'` is in activities; absent otherwise.

The activity sets the server may legitimately declare are constrained by which PSK matched during the [Noise handshake](connection.md#encryption):

| PSK matched | Allowed activity sets |
|---|---|
| [Sendspin PSK](README.md#definitions) | `['pairing']` or any subset of `{'playback', 'management'}` |
| [Sendspin Pairing PSK](README.md#definitions) | `['pairing']` |
| [Sentinel PSK](connection.md#pre-shared-key) | `[]`, `['pairing']`, `['playback']`¹ |

¹ `['playback']` on the Sentinel PSK is only allowed when the client has [unpaired access](pairing.md#unpaired-access) enabled.

`selected_pair_method` MUST be `'pairing_psk'` if and only if the matched PSK is the [Sendspin Pairing PSK](README.md#definitions). It MUST also be a method the client listed in [`supported_pair_methods`](#client--server-clienthello).

**Playback-capable connections.** A connection is *playback-capable* when its `activities` extended with `'playback'` are an allowed set for the matched PSK; a connection already declaring `'playback'` is therefore playback-capable exactly when its `activities` are an allowed set. Only a playback-capable connection MAY carry a non-empty `active_roles`, and it may do so even when `'playback'` is not currently in `activities`.

`server/activate` is *admissible* when it satisfies the constraints above. When one is not admissible, the client rejects it, selecting the response by the first rule that applies:

- If the matched PSK is the [Sentinel PSK](connection.md#pre-shared-key), the client does not have [unpaired access](pairing.md#unpaired-access) enabled, and enabling unpaired access would make the activation admissible - close the connection with [`client/goodbye`](#client--server-clientgoodbye) reason `'pairing_required'`.
- If `activities` is not an allowed set for the matched PSK, or `active_roles` is non-empty on a connection that is not playback-capable - close the connection with [`client/goodbye`](#client--server-clientgoodbye) reason `'unauthorized'`.
- If `'pairing'` is in `activities` with a `selected_pair_method` the matched PSK disallows or the client does not currently offer - reply with [`pair/abort`](pairing.md#client--server-pairabort) reason `method_not_supported`, leaving the connection open. The check uses the live pairing configuration, which may have drifted from [`supported_pair_methods`](#client--server-clienthello); the server may re-activate, or [re-handshake](connection.md#re-handshake) for a fresh advertisement.

**Note:** Servers SHOULD declare the minimal set of activities that reflects the connection's current purpose, and drop an activity as soon as that purpose ends. Admission between competing connections is decided by the highest-ranked declared activity (see [Multiple servers](connection.md#multiple-servers-server-initiated)), so keeping an unused activity declared would degrade multi-server cooperation.

**Note:** Servers normally activate the client's [preferred](README.md#priority-and-activation) version of each role, but MAY omit a role at their discretion (e.g., based on trust level, deployment context, or operator policy). Checking `active_roles` is therefore required to determine what the client may actually use on this session.

**Note:** When a `server/activate` removes a role from `active_roles`, the server first ends that role's output by sending [`stream/end`](#server--client-streamend) for stream roles (`player`, `artwork`, `visualizer`), or a [`server/state`](#server--client-serverstate) with a null role object for state roles (`metadata`, `color`, `controller`) - so the client never holds live data for an inactive role.

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

Sent once the client is ready to report its operational status (`available`), and whenever any state changes thereafter. A player reports `available: true` only after it has established [clock synchronization](#clock-synchronization). The server MUST NOT send binary data to a client before that client has sent its initial `client/state`. When a role becomes active in `active_roles`, send its full state.

The initial message MUST include all state fields. In subsequent messages, the client MAY send only the fields that have changed; the server MUST merge each update into existing state, retaining the last value of any field that is absent. A client MAY instead resend unchanged fields, up to its full state.

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

When a client returns to `available: true`, the server MUST NOT auto-rejoin it to its previous group or restart playback; the client remains in the solo group and rejoins only via an explicit [`switch`](roles/controller/v1.md#switch-command-cycle).

### Client → Server: `client/command`

Client sends commands to the server. Contains command objects based on the client's supported roles.

- `controller?`: object - only if client has `controller` role ([see controller command object details](roles/controller/v1.md#client--server-clientcommand-controller-object))

[Application-specific roles](README.md#application-specific-roles) may also include objects in this message (keys starting with `_`).

### Server → Client: `server/state`

Server sends state updates to the client. Contains role-specific state objects.

Only include fields that have changed. The client will merge these updates into existing state. A leaf field set to `null` should be cleared from the client's state; a whole role object set to `null` clears all of that role's state.

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

Starts a stream for one or more roles. If sent for a role that already has an active stream, updates the stream configuration without clearing buffers. If a parameter change requires rebuffering (e.g., a sample rate change), the receiver handles this internally — the default behavior is to not clear unless the implementation requires it. Implementations may document their specific behavior.

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

**Note:** Clients should use this message to adapt to changing network conditions, CPU constraints, or display requirements. The server maintains separate encoding for each client, allowing heterogeneous device capabilities within the same group.

### Server → Client: `stream/end`

Ends the stream for one or more roles. When received, clients should stop output and clear buffers for the specified roles. This message is expected to be sent when playback is over and the queue is empty. Specifically:

- **Track transitions** (a track ends and the next begins naturally): no stream commands should be sent. The stream continues uninterrupted to support gapless playback and server-inserted crossfade.
- **Seeks** (jumping to a position within the current track): send `stream/clear` instead.
- **Track jumps** (skipping to a different track): treat identically to a seek — send `stream/clear` instead of `stream/end`. Conceptually, the entire queue is a single continuous stream.

Sending `stream/end` in these cases is explicitly prohibited because it signals actual playback termination, causing clients to stop output entirely rather than continue playing.

- `server_transmitted`: integer - timestamp that the server transmitted this message in microseconds
- `roles?`: string[] - roles to end streams for ('player', 'artwork', 'visualizer'). If omitted, ends all active streams

[Application-specific roles](README.md#application-specific-roles) may also be included in this array (names starting with `_`).

### Server → Client: `group/update`

State update of the group this client is part of.

Contains delta updates with only the changed fields. The client should merge these updates into existing state.

- `playback_state?`: 'playing' | 'stopped' - playback state of the group
- `group_id?`: string - group identifier
- `group_name?`: string - friendly name of the group

### Server → Client: `server/unpair`

Sent by a paired server to drop its own pairing record from the client. Valid at any time regardless of the current `activities`; does not require `'management'` in the activity set. No payload fields.

Client behavior:

- Remove the matched pairing record, send [`client/goodbye`](#client--server-clientgoodbye) reason `'unpaired'`, and close the connection.
- If the matched record is a **shared-PSK record** (not bound to a `server_id`; may back other servers - see [Records](management.md#records)), the client MUST NOT remove it. It still sends `client/goodbye` reason `'unpaired'` and closes. Wholesale removal of a shared record requires [`management/remove-record`](management.md#server--client-managementremove-record).
- If the connection's `trust_level` is `'none'` (e.g., a pairing handshake), ignore the message and continue unchanged.

### Client → Server: `client/goodbye`

Sent by the client before gracefully closing the connection. This allows the client to inform the server why it is disconnecting.

Upon receiving this message, the server should initiate the disconnect.

- `reason`: 'another_server' | 'shutdown' | 'restart' | 'user_request' | 'unauthorized' | 'pairing_required' | 'concurrent_attempt' | 'unpaired'
  - `another_server` - client is switching to a different Sendspin server. A client that leaves one server for another MUST send this reason to the server it is leaving. Server SHOULD NOT auto-reconnect but SHOULD show the client as available for future playback
  - `shutdown` - client is shutting down. Server should not auto-reconnect
  - `restart` - client is restarting and will reconnect. Server should auto-reconnect
  - `user_request` - user explicitly requested to disconnect from this server. Server should not auto-reconnect
  - `unauthorized` - the client refused the connection because the server declared an activity set it is not authorized for (e.g., `'management'` without `'user'` [trust level](README.md#definitions)). Server should not auto-reconnect with the same activity set
  - `pairing_required` - the client refused an [unpaired access](pairing.md#unpaired-access) connection because it does not have unpaired access enabled. Server should not auto-reconnect without pairing first
  - `concurrent_attempt` - the client refused the connection because a higher-or-equal-priority connection is already active (e.g., one with `'management'` in its activity set, or a pairing handshake when the incoming connection is also pairing). Server may retry later
  - `unpaired` - the client has processed [`server/unpair`](#server--client-serverunpair) from this server. Server should not auto-reconnect

**Note:** When the device is powering off or otherwise not coming back and no more specific reason applies, clients SHOULD send `shutdown`.

**Note:** Clients may close the connection without sending this message (e.g., crash, network loss), or immediately after sending `client/goodbye` without waiting for the server to disconnect. When a client disconnects without sending `client/goodbye`:

- On a connection whose `activities` are empty, or include `'playback'`, servers should assume the disconnect reason is `restart` and attempt to auto-reconnect.
- Otherwise, servers should treat the drop as a session termination and not auto-reconnect; resumption, if desired, is operator-driven.
- Servers should also apply backoff on repeated Noise-handshake failures to avoid tight reconnect loops when a long-term PSK has become invalid (e.g., after a client factory reset). After repeated consecutive failures, the server SHOULD NOT keep auto-reconnecting until there is reason to expect success (e.g., the operator re-initiates pairing or network conditions change).
