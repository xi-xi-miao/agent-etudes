What `dev/` and `hidden/` hold, the dev seeds, the id pattern, byte-for-byte reproducibility and the post-round protocol are in [`../README.md`](../README.md) ("Dev set and hidden set" and "Dev instances, hidden instances, checkpoints").

To regenerate one committed dev instance in place:

```sh
uv run python challenges/c001/tools/generate.py \
    --tier 2 --seed 2003 --id c001-t2-dev-03 \
    --out challenges/c001/instances/dev/c001-t2-dev-03.json
```
