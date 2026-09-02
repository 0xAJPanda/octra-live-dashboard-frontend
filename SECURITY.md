# Security notes

## Included in browser telemetry

- Public validator address and validator state
- Epoch, transaction index, and account count
- Voting, RPC, sync, and process health
- Aggregate peer counts
- Coarse CPU, memory, disk, load, and uptime metrics

## Explicitly excluded

- Validator private keys, mnemonic, seed, and recovery data
- Wallet and configuration file contents
- Environment variables and command lines
- Host IP addresses, peer addresses, ports, and SSH data
- Full logs and arbitrary node/RPC responses

The app should remain loopback-only. Public deployment requires a separate authenticated TLS reverse proxy and should not reuse the validator node's administrative credentials.
