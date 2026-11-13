# Oasis Smart Lights for Home Assistant

Control Oasis (Mixtiles) smart bulbs from Home Assistant, from anywhere, without the Oasis app.

## Install

**HACS (recommended)**

1. HACS → three-dot menu → Custom repositories.
2. Add this repository, category "Integration".
3. Install "Oasis Smart Lights", then restart Home Assistant.
4. Settings → Devices & Services → Add Integration → Oasis.

**Manual**

Copy `custom_components/oasis` into your Home Assistant `config/custom_components/` directory and restart.

## Sign in

The integration asks which kind of Oasis account you have.

**Email and password.** Enter the same credentials you use in the app.

**Apple or Google.** These accounts have no password, so Home Assistant shows a sign-in link. Open it,
sign in, and your browser will finish on an error saying the address is invalid. That error is the
success case: the final address belongs to the Oasis phone app, so a browser cannot open it. Copy the
whole `rainmaker://...` address and paste it back into Home Assistant.

## What you get

One light entity per bulb, with on/off, brightness, and colour temperature. Parameter names and colour
temperature limits are read from each bulb rather than hardcoded, because vendors on this platform
rename and re-range them freely.

## How it works

Oasis bulbs are ESP32-C6 devices running [ESP RainMaker](https://rainmaker.espressif.com/). The app
controls them two ways: locally over BLE Mesh, and remotely through a RainMaker deployment on AWS. BLE
Mesh is why the app only works when you are near the lights. This integration uses the cloud path, so
distance stops mattering.

## Limitations

Control depends on Mixtiles' servers. The bulbs expose no local network API at all: every TCP port is
closed, they answer no discovery protocol, and they run no mDNS responder, so there is no local
fallback and no Matter support.

A bulb acknowledges a cloud command in about one second, but it reports its state to the cloud only
about every 20 seconds. Home Assistant therefore shows a commanded value at once and holds it for 30
seconds, then until the cloud agrees, for at most 60 seconds. Without the hold, two commands sent
close together made the entity flip to the first command's state when its late report arrived.

Measured on firmware 2.32.7 on 2026-11-13: the RainMaker command API (`POST /user/nodes/cmd`,
`cmd: 1`, `data: {"params": {...}}`) returned the bulb's own success reply 0.8 to 1.1 seconds after
seven commands, while the bulb's state record for the same commands appeared 1 to 15 seconds later,
on a 20 second grid. The Oasis app sends its cloud commands with the same `PUT /user/nodes/params`
call this integration uses. How fast the lamp itself changes was not measured.

Home Assistant polls every 10 seconds. A change made in the Oasis app appears here after the bulb's
next report plus one poll, so within about 30 seconds.
