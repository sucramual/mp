# /age report: acme/widgets#512

Head reviewed: `b7d41e09c3a25f8e6d1c0b9a8f7e6d5c4b3a2918`. Dimensions: all thirteen.

## blocker

None.

## high

None.

## medium

- `src/settings_cache.py:15`: `get_settings` returns the cached dict itself. A caller that changes the returned dict changes the cache for every later request of that tenant for up to 60 seconds. Return a copy, or document that callers must not change it.

## low

- `src/settings_cache.py:12`: `time.time()` follows wall-clock changes. `time.monotonic()` is safer for a TTL.
