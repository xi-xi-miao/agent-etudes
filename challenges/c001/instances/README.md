`dev/` holds the 15 committed development instances (tiers 1-3 x 5 seeds each); solve these during the session.

`hidden/` stays empty until the round closes: the organizer then publishes the secret seeds and commits the generated instances in the same PR (`tools/make_hidden.sh --help` spells out the protocol).

Instance ids follow `c001-t<TIER>-dev-<NN>` and `c001-t<TIER>-hidden-<NN>`, and every file's name is its own `instance_id` plus `.json`.

The dev seeds are `1001-1005` (tier 1), `2001-2005` (tier 2) and `3001-3005` (tier 3); `<NN>` is the last two digits of the seed. Every committed file is reproducible byte for byte, and `tests/test_generate.py` asserts exactly that:

```sh
uv run python challenges/c001/tools/generate.py \
    --tier 2 --seed 2003 --id c001-t2-dev-03 \
    --out challenges/c001/instances/dev/c001-t2-dev-03.json
```
