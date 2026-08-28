## Management

This section covers the management commands a paired server may issue.

Management commands are scoped to connections with `'management'` in their [`activities`](messaging.md#server--client-serveractivate). When the server adds `'management'` to the activity set, the client validates that the matched PSK is a [long-term PSK](README.md#definitions) (i.e. the server is paired); if not, it closes the connection with [`client/goodbye`](messaging.md#client--server-clientgoodbye) reason `'unauthorized'`. If a `management/*` message arrives on a connection without `'management'` in activities, the client replies with [`management/result`](#client--server-managementresult) `permission_denied`.

All `management/*` requests are answered by a single [`management/result`](#client--server-managementresult) message. At most one management request may be in flight per connection; in-order WebSocket delivery makes the reply unambiguous.

### Records

Read, create, and remove the pairing records stored by the client. Each record holds a [long-term PSK](README.md#definitions), so any session it authenticates is [paired](README.md#definitions). Records come in two kinds:

- **Stored-pubkey records** bind a long-term PSK to a specific `server_id`.
- **Shared-PSK records** hold a PSK without an associated `server_id` - the same record may authenticate any server that holds the PSK.

Across all record operations, a record is identified by its `psk_id` (see [Pre-Shared Key](connection.md#pre-shared-key) for the derivation).

#### Server → Client: `management/list-records`

No payload fields.

On success, `data: { records: object[] }`. Each entry in `records`:

- `psk_id`: string
- `server_id?`: string - present for stored-pubkey records, absent for shared-PSK records
- `used`: boolean - `true` once a server has authenticated a session with this record's PSK

Possible outcomes: `ok`, `permission_denied`.

#### Server → Client: `management/add-record`

Add a pairing record directly.

- `psk`: string - 43-character base64url-encoded 32-byte [long-term PSK](README.md#definitions) (no padding)
- `server_id?`: string - present for stored-pubkey records, absent for shared-PSK records

A `psk` whose `psk_id` is already known, whether as a record or as the Sentinel PSK or the client's pairing PSK (see [Pre-Shared Key](connection.md#pre-shared-key)), is rejected as `already_exists`.

Possible outcomes: `ok`, `permission_denied`, `already_exists`, `invalid`, `storage_exhausted`.

#### Server → Client: `management/remove-record`

Remove a pairing record.

- `psk_id`: string

Removing the requester's own record closes the management session with [`client/goodbye`](messaging.md#client--server-clientgoodbye) reason `'unauthorized'` after the response.

A record that is still referenced by a `record_mode.psk_id` (see [Record mode](#record-mode)) cannot be removed.

Possible outcomes: `ok`, `permission_denied`, `invalid`, `not_found`.

### Pairing Config

Commands for inspecting and modifying the client's pairing configuration.

#### Server → Client: `management/get-pairing-config`

No payload fields.

On success, `data` is shaped as:

- `pairing_psk`: object
  - `enabled`: boolean
- `static_pairing_code?`: object
  - `enabled`: boolean
- `dynamic_pairing_code?`: object
  - `enabled`: boolean
  - `escalated`: boolean - `true` when the method is [escalated](pairing.md#failure-counter) to gesture-gating by its failure counter
- `record_mode`: object - see [Record mode](#record-mode)
- `unpaired_access`: object - see [Unpaired Access](pairing.md#unpaired-access)
  - `enabled`: boolean

A pairing-code method object is absent if the client does not implement that method.

Configured secrets (the pairing PSK and the static pairing code) are not returned; use [`management/set-pairing-config`](#server--client-managementset-pairing-config) to rotate them.

Possible outcomes: `ok`, `permission_denied`.

#### Server → Client: `management/set-pairing-config`

Modify pairing config.

- `pairing_psk?`: object
  - `enabled?`: boolean
  - `psk?`: string - 43-character base64url-encoded 32-byte PSK (no padding); replaces the configured pairing PSK
- `static_pairing_code?`: object
  - `enabled?`: boolean
  - `code?`: string - 8 decimal digits; replaces the configured static pairing code
- `dynamic_pairing_code?`: object
  - `enabled?`: boolean
- `record_mode?`: object - see [Record mode](#record-mode)
- `unpaired_access?`: object - see [Unpaired Access](pairing.md#unpaired-access)
  - `enabled?`: boolean

The request applies as a patch: only fields present in the payload are written, and any absent field (including an absent method object) leaves the corresponding stored value unchanged. Fields set on a method the client does not implement are rejected as `invalid`. Enabling `static_pairing_code` with no static pairing code configured and none supplied in the same request is likewise rejected as `invalid`. A `pairing_psk.psk` whose `psk_id` collides with a candidate PSK in a different category (the Sentinel PSK or a stored record; see [Pre-Shared Key](connection.md#pre-shared-key)) is rejected as `already_exists`.

Possible outcomes: `ok`, `permission_denied`, `already_exists`, `invalid`, `storage_exhausted`.

#### Record mode

When a server completes pairing via any method, the resulting record is created according to the client's `record_mode`, a setting configured via [`management/set-pairing-config`](#server--client-managementset-pairing-config).

`record_mode?`: object
- `psk_id`: string - the shared-PSK record used as the storage-exhaustion fallback.

The client creates a stored-pubkey record bound to the server, holding a freshly generated [long-term PSK](README.md#definitions). If storage is exhausted, it instead admits the server under the shared-PSK record at `psk_id`, which becomes that server's long-term PSK.

`psk_id` MUST reference a shared-PSK record. This constraint is enforced at configuration time: any management request that would set `psk_id` to a missing or stored-pubkey record is rejected, and the referenced shared-PSK record cannot be removed while the reference exists. Both operations are rejected as `invalid`. By default, `psk_id` points to a pre-provisioned shared-PSK record.

The pre-provisioned record's PSK MUST be drawn from a [CSPRNG](README.md#definitions) per device and MUST NOT be a fixed default shared across devices.

### Server → Client: `management/open-pairing-window`

Opens a [pairing window](pairing.md#pairing-window) in place of the operator gesture.

No payload fields.

A no-op `ok` when a window is already open; rejected as `invalid` when no pairing-code method is enabled.

Possible outcomes: `ok`, `permission_denied`, `invalid`.

### Client → Server: `management/result`

Response to a `management/*` request. The at-most-one-in-flight rule (see [Management](#management)) lets the server match each reply to its request by ordering alone, so no request-identifier field is carried.

- `result`: string - result code. See each request's outcomes line for the subset that applies.
  - `ok` - operation completed and any state change has been persisted
  - `permission_denied` - the request was issued outside a valid management session
  - `already_exists` - the request conflicts with an existing entry on the client
  - `invalid` - the request payload is malformed, contains an out-of-range value, omits a field required for the chosen operation, or violates a referential constraint
  - `not_found` - the request targets an identifier (e.g., `psk_id`) that does not exist on the client
  - `storage_exhausted` - the client cannot persist the change due to full storage
- `data?`: object - operation-specific response payload. Present only when the in-flight request defines one and `result` is `ok`; see each request for the shape.
- `storage?`: object - storage accounting; a client that tracks bounded storage includes it on every result except `permission_denied`. See [Storage accounting](#storage-accounting).

#### Storage accounting

Records (and, on some clients, operator-set pairing secrets) share one storage pool. A client that can bound this pool reports it in the `storage` key, letting a server show remaining capacity and predict which operations will succeed; a client whose storage is effectively unbounded or of unknown size omits the key, and the server relies on `storage_exhausted` alone.

- `free`: integer - currently free space.
- `capacity`: integer - total pool size.
- `cost_individual`: integer - what a new stored-pubkey record consumes.
- `cost_shared`: integer - what a new shared-PSK record consumes.

All four use one client-chosen unit (bytes, slots, ...), treated as opaque - a server uses only ratios and quotients, e.g. `(capacity - free) / capacity` or `free / cost_individual`. A record of a given kind can persist when `free` is at least that kind's cost; `storage_exhausted` however stays authoritative.

A secret set via [`set-pairing-config`](#server--client-managementset-pairing-config) may also draw on the pool but isn't covered by these costs.

The object always carries `free`; `capacity` and the costs appear additionally on [`list-records`](#server--client-managementlist-records) and [`get-pairing-config`](#server--client-managementget-pairing-config) results.
