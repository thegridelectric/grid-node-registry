# STAGING SNAPSHOT — PLEASE ONLY USE IN DEV

This snapshot contains STAGING vocabulary: mutable words that run on dev
brokers only. It MUST NOT be used against hybrid or production brokers.

Staging words in this snapshot:

- type g.node.create.cmd:000

When these words promote to published, rebuild without `--allow-staged` to
get a publication-grade snapshot (and this file disappears).
