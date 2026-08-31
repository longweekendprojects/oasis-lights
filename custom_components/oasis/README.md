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

The cloud reports state 15 to 25 seconds after a change. Home Assistant updates the entity immediately
on a command, then reconciles on the next poll, so brief disagreement after a change is expected.

Changes made in the Oasis app appear here within the 30 second polling interval.
