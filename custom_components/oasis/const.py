"""Constants for the Oasis smart light integration."""

from __future__ import annotations

DOMAIN = "oasis"

# ESP RainMaker deployment behind the Oasis app, recovered from the app's bundled
# .env and confirmed against the live API.
API_BASE = "https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/dev/v1"

# Cognito hosted UI. The redirect URI comes from the flutter_web_auth_2
# CallbackActivity intent-filter in the app's AndroidManifest.
COGNITO_BASE = "https://applogin.heyoasis.com"
CLIENT_ID = "20hc2tbnm5cqipo83tq7fr6lt1"
REDIRECT_URI = "rainmaker://com.mixtiles.oasis/success"
OAUTH_SCOPE = "openid email profile"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_AUTH_MODE = "auth_mode"
AUTH_MODE_PASSWORD = "password"
AUTH_MODE_OAUTH = "oauth"

DEFAULT_SCAN_INTERVAL = 30

# The bulbs report colour temperature in Kelvin. These bounds are overridden per
# device whenever the node's own parameter config declares them, which this
# firmware does not, so they were measured instead: a request for 6500 K comes
# back as 4000 K, while 1800 K is accepted as sent.
DEFAULT_MIN_KELVIN = 1000
DEFAULT_MAX_KELVIN = 4000

# The Oasis app offers named warmth presets rather than a raw Kelvin slider.
# These mirror it, spread across the range the hardware actually honours, with
# Candle matching the 2000 K the app reports for its warmest setting.
PRESETS: dict[str, int] = {
    "Bright": 4000,
    "Neutral": 3600,
    "Soft": 3200,
    "Glow": 2800,
    "Amber": 2400,
    "Candle": 2000,
    "Red": 1000,
}

# RainMaker vendors rename standard parameters freely, so every lookup goes
# through these candidate lists rather than a hardcoded name.
PARAM_POWER = ("Power", "power", "switch")
PARAM_BRIGHTNESS = ("Brightness", "brightness")
PARAM_CCT = ("CCT", "Temperature", "temperature", "color_temp")
