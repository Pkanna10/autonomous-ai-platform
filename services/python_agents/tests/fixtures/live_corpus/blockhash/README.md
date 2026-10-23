# blockhash

Hashes a generated disk image block by block (SHA-256 over every block followed
by its block number) and prints the image digest.

```
python -m blockhash.main
```

The image is generated deterministically, so the output is the same on every
run.
