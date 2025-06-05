# The Resonate Protocol

_This is raw, unfiltered and experimental._

Resonate is a multi-room music experience protocol. The goal of the protocol is to orchestrate all devices that make up the music listening experience. This includes outputting audio on multiple speakers simultaneously, screens and lights visualizing the audio or album art, and wall tablets providing media controls.

# Definitions

* Source: a Resonate server. Generates an audio stream, manages all the players, provides metadata etc.
* Player: a Resonate client that can play audio, visualize audio or album art or provide music controls

# Establishing a Connection

Players will announce their presence via mDNS on the `resonate` type.

Resonate communicates over WebSockets on the path `/resonate`. Recommend port is `8927`.

Resonate servers will also be able to connected to for supporting browsers, mobile apps, and other devices that can run a WebSocket client.

# Communication

Once the connection is established, Player and Source are going to talk.

Websocket Text messages are used to send JSON payloads.

Websocket binary messages are used to send audio chunks.

Message format is as follows:

```javascript
{
  "type": "session/start",
  "payload": { ... },
}
```

## Player to Source: `player/hello`

Information about the Output device

* `player_id` string, to uniquely identify the player for groups and de-duplication
* `name` string,
* `support_codecs` string\[\], Supported codecs listed in order of highest priority to lowest
* `support_channels` number\[\], Number of channels (in order of priority)
* `support_sample_rates` number\[\], Supported sample rates (also in order of priority)
* `support_bit_depth` number\[\], Bit depth (also in order of priority)
* `buffer_capacity` number, Buffer capacity size in bytes
* `role` string, what the device wants to “play”. It could be used for voice, display artwork or remote control only device. (not specced out, keep option out)
* `support_streams` string\[\] Supported streams (can be media, or voice (not supported now)).
* `support_picture_formats` string\[\], Supported media art image formats
* `media_display_size` string | null, Cover media display size (null for none)

## Source to Player: `source/hello`

Information about the source

* `source_id` the identifier of the source
* `name` the name of the source

## Player to Source: `player/time`

Sends current internal clock timing (in microseconds) to source

* `player_transmitted` players internal clock, in microseconds

## Source to Player: `source/time`

Response to the players time message with info to establish a clock offsets

* `player_transmitted` players internal clock, in microseconds
* `source_received` timestamp that the source received the player/time message
* `source_transmitted` timestamp that the source transmitted this message

## Source to Player: `session/start`

When a player needs to start playing.

* `session_id`, string: identifier for the session
* `codec`, string: codec to be used
* `sample_rate`: number, sample rate to be used
* `channels`, number: channels to be used
* `bit_depth`, number: bit depth to be used
* `now`, signed bigint64: current time on the server as unix timestamp in microseconds
* `codec_header`, XXXX | null: Codec header (if necessary; e.g., FLAC)

Edge cases:

* If a player receives a session/start while it’s already playing that stream type, it should stop the existing one and adopt new one.

## Source to Player: `session/end`

Player should stop streaming, clear metadata etc.

## Source to Player: `metadata/update`

This is deltas. Has to be merged into what exists. Source ensures first one is the full one. If a field is optional and has to be nullified, the value will be set to `null`.

Paulus: I just added some fields to get ball rolling
Paulus: should all fields be included or be partial updates?

* `title` string; optional
* `artist` string; optional
* `album` string; optional
* `year` number; optional
* `track` number; optional
* `group_members` string\[\]: player IDs
* `support_commands` string\[\]: array containing a subset of these: "play" | "pause" | "stop" | "seek" | "volume"
* `repeat` "off" | "one" | "all";
* `shuffle` boolean;

## Player to Source: `stream/command`

Control the stream that we’re playing

* `command` one values listed in `metadata/update` field `support_commands`

## Player to Source: `player/state`

The player can be controlled via physical controls or other remote APIs, like ESPHome API via HA. For example, player will tell source that it got controlled.

Paulus: should all fields be included or be partial updates?

* `state`
  * `playing` active session, and outputting
  * `paused` active session, not consuming buffer
  * `idle` no active session
* `volume` integer 0-100
* `muted` boolean

## Player to Source: fetch groups

Fetches all groups available to join on the server

* Include state of each group: playing, paused, or idle

## Player to Source: `group/join`

When a player wants to join a group

Response is a metadata/update. You will also get a response end message if a stream is playing.

## Player to Source: `group/unjoin`

When a player wants to leave group

Response is a metadata/update

## Source to Player: `volume/set`

* `volume`, number: Volume range: 1-100 (integer)

## Source to Player: `mute/set`

* `Mute`, bool

## Source to Player: binary message

The binary message from source to player is always an audio chunk.
If no session is playing, the binary message should be rejected.
Range is inclusive of both start and end.

* Byte 0: message type

### Binary message media art. Type 2

* Byte 1: codec
* Rest of bytes: art

### Binary message: audio chunk. Type 1

* Byte 1-8: timestamp (signed int64)
* Byte 9-12: number of samples (per channel) in chunk
* Rest of bytes: encoded audio frame
