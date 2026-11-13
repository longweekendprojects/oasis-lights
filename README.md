# Oasis Lights

Control the Oasis (Mixtiles) smart bulbs from anywhere, including from Home Assistant, without the vendor app.

## Quick start

```bash
# one time, for Apple or Google sign-in (no password exists for these accounts)
oasis-api auth
oasis-api auth --redirect '<paste the rainmaker:// URL you land on>'

# one time, for email + password accounts instead
security add-generic-password -U -a "you@example.com" -s oasis_password -w

oasis-api list            # show every bulb and its current state
oasis-api on              # turn everything on
oasis-api -d "Bedroom" off
oasis-api -d "Bedroom" brightness 40
```

## Why the app only works at home

The Oasis app drives the bulbs over **BLE Mesh** when you are nearby. Every command class in the app is
Bluetooth (`BleSendDeviceCommand`, `BleSendRoomCommand`, `LightBrightnessAndTemperatureCommand`), so
Bluetooth range, not Wi-Fi, is what ties you to the house. The bulbs separately keep an outbound
connection to an **ESP RainMaker** deployment on AWS, and the app falls back to that as its "remote
command" path. This tool uses the cloud path, so distance stops mattering.

Routing a phone through a home Tailscale exit node also makes the app work remotely, which confirms the
fallback path is reachable and functioning rather than blocked at the account level.

## The device

| Property | Value |
|---|---|
| Model | Oasis Ambient GLS bulb |
| Hostname | `Oasis-AMBGLS604500101` |
| Vendor MAC | `ac:eb:e6:*` (Espressif) |
| SoC | ESP32-C6-Mini |
| Firmware stack | ESP RainMaker |
| Local control | BLE Mesh (no LAN control surface at all) |
| Open TCP ports | none, across all 65535 |
| Open UDP ports | one ephemeral outbound socket only |
| App | `com.mixtiles.oasis` (Flutter) |

The bulb exposes no local API. A full TCP sweep and an ICMP-unreachable UDP sweep both came back empty,
and it runs no mDNS responder, which also rules out Matter. Cloud is the only network control path.

## API

Base URL: `https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/dev/v1`

This is a stock ESP RainMaker deployment, so the published RainMaker REST contract applies.

| Call | Purpose |
|---|---|
| `POST /login2` `{user_name, password}` | returns `accesstoken` / `refreshtoken` |
| `POST /login2` `{user_name, refreshtoken}` | refresh without re-sending the password |
| `GET /user/nodes?node_details=true` | node list with config, params, connectivity |
| `PUT /user/nodes/params` | set params: `[{node_id, payload:{<device>:{Power:true}}}]` |

Send the token in a bare `Authorization` header (no `Bearer` prefix). The client tries the Cognito
`id_token` and `access_token` in turn and remembers whichever the API Gateway authorizer accepts.

### Sign-in without a password

Accounts created with Apple or Google have no password, so `/login2` cannot be used. Those accounts go
through the Cognito hosted UI instead, using PKCE:

| Setting | Value |
|---|---|
| Hosted UI | `https://applogin.heyoasis.com` |
| Client ID | `20hc2tbnm5cqipo83tq7fr6lt1` (public client, no secret) |
| Redirect URI | `rainmaker://com.mixtiles.oasis/success` |
| Identity provider | `SignInWithApple` |
| Apple client ID | `com.mixtiles.oasis.prod` |

The redirect URI comes from the `flutter_web_auth_2` CallbackActivity intent-filter in the app's
AndroidManifest. Because it is a custom scheme, a desktop browser cannot follow it; the authorization
code still appears in the URL, which is why `auth --redirect` accepts the whole URL pasted back.

## Configuration

Credentials live in the macOS Keychain under service `oasis_password`; the account field holds the
email address. Nothing sensitive is stored in this repo. Access tokens are cached at
`~/.config/oasis/tokens.json` with mode 0600 and refreshed automatically.

## Home Assistant

The supported path is the native integration in `custom_components/oasis`, which talks to the Oasis
cloud directly and does not need this bridge running. Install it with the single command from
`GET /install`, then pick "Import from the Oasis bridge on this network" and select Submit: the bridge
hands over the signed-in session, so there is no token to copy and no sign-in to repeat.

Moving the credential by hand proved unreliable. A refresh token is roughly 1800 characters, the
clipboard is easily clobbered mid-task, and repeating the Apple sign-in produces sessions the Oasis API
refuses, so handing the working session over machine-to-machine is the only dependable route.

The YAML bridge below remains as a fallback for anyone who would rather not install a custom component.

### Updating without SSH

Home Assistant OS exposes no SSH port by default, but the File editor add-on can run shell commands in a
container that mounts the config directory. From a browser signed in to Home Assistant, POST to its
ingress path `/api/exec_command` with:

```sh
sh -c "curl -sfL http://<mac>:8099/custom_component.tar.gz -o /tmp/o.tgz && tar xzf /tmp/o.tgz -C /homeassistant/custom_components"
```

Two traps make this worth writing down. Add-ons see Home Assistant's config at `/homeassistant`, not at
`/config`, which is the add-on's own private folder, so writing to `/config` succeeds and Home Assistant
never sees the files. And `exec_command` runs without a shell, so an unwrapped `&&` chain is tokenized
into the first command's arguments; the `sh -c` wrapper is required.

Reach Supervisor through the WebSocket `supervisor/api` command rather than `/api/hassio/...`, which
returns 401 for a frontend token. The Terminal & SSH add-on accepts an `init_commands` option and
reports success, but does not run it, so it is not a deploy path.

### The YAML fallback

Home Assistant cannot reach the Oasis cloud itself. The account signs in with Apple, and the tokens and
their refresh cycle live on the Mac. `oasis_bridge.py` keeps that credential handling here and exposes a
plain local HTTP API, so Home Assistant needs no account and no token of its own.

```bash
./oasis_bridge.py                 # foreground, listens on 0.0.0.0:8099
launchctl load ~/Library/LaunchAgents/com.oasis.bridge.plist   # or run it permanently
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /lights` | every light, in the units Home Assistant expects |
| `GET /light/<slug>` | one light |
| `POST /light/<slug>/set` | `{"power":true,"brightness_pct":40,"kelvin":3000}` |
| `GET /homeassistant.yaml` | generated config for the lights you actually own |
| `GET /custom_component.tar.gz` | the integration, with this bridge's address baked in |
| `GET /credentials` | hands the signed-in session to Home Assistant (private networks only) |
| `GET /install` | the one command that installs the integration and restarts HA |
| `GET /dashboard.yaml` | a dashboard laid out like the phone app |

The bridge converts units in both directions: RainMaker speaks brightness as a percentage and colour
temperature in Kelvin, while Home Assistant wants 0-255 and mireds.

To install, fetch the generated config and paste it into `configuration.yaml`, then restart Home
Assistant:

```bash
curl http://192.168.50.49:8099/homeassistant.yaml
```

A copy is committed here as `homeassistant.yaml`. Regenerate it after adding or renaming bulbs, since
the REST sensors are bound to list positions. Entity keys are namespaced (`light.oasis_*`) because a
bulb named "Light" would otherwise become `light.light`.

Set `OASIS_BRIDGE_TOKEN` to require an `X-Auth-Token` header. It is unset by default, which means anyone
on the LAN can toggle the lights.

### Remote control

Because the bridge talks to the Oasis cloud rather than the bulb, Home Assistant drives these lights
whether or not you are home. Reaching Home Assistant from outside the house is the only remaining piece,
and that is already solved by your existing remote access.

## Controls

Each bulb gets a light entity with power and brightness, plus a "Warmth" select carrying the
named presets the phone app uses: Bright, Neutral, Soft, Glow, Amber, Candle, Dusk, Maui, and Red. The select reports the
preset nearest the bulb's actual colour temperature, so a warmth chosen in the app or by the bulb's own
schedule still shows correctly rather than reading as blank.

`GET /dashboard.yaml` generates a layout matching the app, a power and brightness row per bulb with the
preset buttons beneath. Paste it into the dashboard's raw configuration editor.

The firmware clamps colour temperature at 4000 K even though it accepts higher values without
complaint, and it honours values below 2000 K. The presets span the range it actually applies. Candle
matches the 2000 K the app reports for that setting, Dusk is 1500 K, Maui is 1100 K, and Red is 1000 K.

## Caveats

Control depends on Mixtiles' servers and on the Apple sign-in continuing to work. There is no local
fallback: the bulb exposes no LAN control surface whatsoever.

Writes are accepted immediately but the cloud's reported state lags roughly 15 to 25 seconds behind.
Read a value back after a settle, not straight away, or it will look like the write was ignored.

For permanent local control the ESP32-C6 can be reflashed with ESPHome, which makes the bulb a
first-class local Home Assistant device with no cloud, account, or token refresh. That needs physical
disassembly and a USB-UART adapter, and it ends support from the Oasis app.

## Development

Both `oasis_api.py` and `oasis_bridge.py` depend only on the Python standard library. `param_key()`
resolves parameter names from each node's own config rather than hardcoding them, because RainMaker
vendors rename `Power`, `Brightness`, and `CCT` freely.

How the device was identified, in case it needs redoing for another vendor: reverse DNS against the
router (`dig -x <ip> @192.168.50.1`) named the bulb after MAC lookups, mDNS, SSDP, and port scanning had
all failed. The protocol came from decompiling the app rather than from packet capture, because Wi-Fi
encrypts client-to-client traffic per station, so a third machine cannot sniff a phone talking to a bulb
even with root.
