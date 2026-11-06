# Join the SN2 validator scoring pilot

Run the DaniLabs verifier alongside your existing Finney SN2 setup. Use a
Linux CPU host with Python 3.12, Git, and outbound HTTPS and WSS. Finney RPC
needs to serve the finalized epoch boundaries. The public Finney archive
endpoint is suitable when a lite node has pruned the start of the epoch.

## Install and run

```sh
git clone https://github.com/DaniLabsAI/subnet.git
cd subnet
git rev-parse HEAD
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
cp config/observer.example.json config/observer.local.json
.venv/bin/python - <<'PY'
import json
from pathlib import Path

path = Path('config/observer.local.json')
config = json.loads(path.read_text())
config.update(netuid=2, chain_endpoint='wss://archive.chain.opentensor.ai:443',
              weight_submission_mode='legacy-commit-reveal')
path.write_text(json.dumps(config, indent=2) + '\n')
PY
PYTHONPATH=src .venv/bin/python -m danilabs_validator \
  --config config/observer.local.json status
PYTHONPATH=src .venv/bin/python -m danilabs_validator \
  --config config/observer.local.json score \
  --reports-config config/reports.example.json
```

`status` reports the finalized chain, runtime, and owner registration. The
template starts without operator identity pins, so its signing guard will
show as blocked. For a read-only check of your own UID, add your **public**
`validator_hotkey` to the local configuration. The `score` command verifies
the signed report, checks its epoch and miner registrations against Finney,
then emits JSON. It works without a registered hotkey or permit. A permit is
only relevant to live validation and the unsigned call preview.

A successful run shows `status: ready`, a `report_id` and `report_sha256`,
`epoch_end_block`, and a `candidate_weights` array. An empty array can be
normal when an epoch contains no eligible measurements. Wait for publication
if Finney has just finalized a new epoch, then rerun the same command. Use the
repository’s report key pin and compare runs for the same report ID and hash.
[Report fields and scoring rules](validator-reports.md)

## Confirm your setup

Share the Git commit, report ID or epoch end block, and whether verification
returned `ready` in [DaniLabs #validators](https://discord.com/channels/1555079929148866610/1564448334322602177).
Include your public SN2 UID if you already operate one. Include a sanitized error
if verification fails. Keep wallet material and access credentials on your host.

The pilot leaves your current production process in place. DaniLabs signs only
the reviewed owner-destination burn policy on its own validator. Operators
planning a live signer migration should coordinate it in #validators and review
the [signer requirements](production-signer.md) and [runtime 488 review](runtime-488.md)
before enabling any Finney signing. A code update alone does not approve a runtime
or change the weight policy.
