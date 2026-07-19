"""S2 read-only adapter layer (spec Phase S2).

Adapters translate a live or frozen source into a normalized
``ObservationSnapshot`` consumed by the existing pure S1 engine. They perform
NO writes and NO Federation-world mutations. An unavailable or unreadable
source yields ``status="unknown"`` -- never a fabricated "healthy".

These modules are deliberately OUTSIDE the S1 pure-engine import graph
(schema.py / checks/* / cli.py). S1 stays pure; S2 adapters feed it snapshots
that are byte-compatible with S1 frozen fixtures.
"""
