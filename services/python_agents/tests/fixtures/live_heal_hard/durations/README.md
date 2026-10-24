# durations

Durations in our configuration files are written with a unit on every
number: `90s`, `15m`, `1h30m`.

A bare number such as `90` is refused with a `ValueError`. This is
deliberate (incident 2025-03: a timeout of `90` meant minutes to the person
who wrote it and seconds to the service). Write `90s` or `90m`.
