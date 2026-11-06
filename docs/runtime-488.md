# Runtime 488 review

[Runtime 488](https://github.com/RaoFoundation/subtensor/releases/tag/v488)
identifies the source as `b6a81d144078eac18bd25c3af7cb31579bb670f3`. The
official compressed WASM SHA-256 is
`fbcacb1d5d6b320c68cf4098465039bd7667772abc542596baf4e2456d5c3c15`.
Its Blake2-256 hash
`3147daab804046184359d8a929cb333d75f490323b9e1327887a172c64eafa94`
matched finalized Finney `:code`. Signer preflight checks that code hash in
addition to the runtime version. Transaction version is still 1.

Compared with v486, the legacy commit/reveal and epoch activity implementation
files are unchanged. The extrinsic decoder now has paths for new hashed-account
signatures and retains legacy signed version-4 dispatch. The reviewed miner
incentive withholding still stores the settled ratio as U96F32 in `MinerBurned`.
The finalized SN2 settlement used the Burn mode and recorded 4,294,967,296 bits
under runtime 488, which is 100% using the reviewed encoding.

The isolated acceptance executed the actual runtime's commit and reveal via
`BlockBuilder_apply_extrinsic` using a finalized state fork, a mock signature,
and a manual change to the fork's epoch index to exercise the two-epoch reveal
delay. Both calls succeeded. The final fork row was `[[14, 65535]]`. The fork
does not establish a new production settlement or exercise the production key.
