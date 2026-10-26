# Runtime 486 review

The reviewed source is
[`72323e13249c9e25c7e792a2b3c08502c84651d5`](https://github.com/RaoFoundation/subtensor/commit/72323e13249c9e25c7e792a2b3c08502c84651d5),
published as [runtime 486](https://github.com/RaoFoundation/subtensor/releases/tag/v486).

The upstream comparison from the reviewed runtime 484 changes the runtime version,
deployment tooling, and weight accounting for the contract chain extension's
stake-availability getter. It leaves the Subtensor pallet's weight submission,
commit/reveal, owner registration, validator eligibility and coinbase code unchanged.
The runtime transaction version remains 1.

The official compressed WASM has SHA-256
`46a07a802272d3b66f6e67213be8cc4c9b3f8788e91153686f192077d3df4457`
and Blake2-256 code hash
`49781ac4cfda0ac6cf6e53cfceea7c728394d9c28da7881f47e3fbfbc239800f`.
The release deployment record identifies mainnet block 9369470.

The signer accepts runtime 486 only with its exact source commit in the separate
operator policy. Adding this review does not enable Finney or replace any hotkey.
Run the official WASM on localnet and verify finalized commit/reveal and full
miner-incentive burn before activating the corresponding production policy.

On October 26, the downloaded WASM matched the finalized Finney code hash. All
38 unit tests passed on macOS and the Arm validator host. The private chain then
verified automatic recovery after a signer crash, a finalized reveal, and full
miner-incentive burn in a subsequent runtime-486 epoch. Its existing chain history
was preserved. These checks submitted no Finney transactions.
