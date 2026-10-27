"""Golden runtime encoding vectors captured from the deployed SDK9 implementation."""
import unittest

from danilabs_validator.weights import generate_weight_hash

ALICE = '5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY'


class CommitmentTests(unittest.TestCase):
    def test_runtime_golden_vectors(self):
        for uids, values, salt, version, expected in [
            ([14], [65535], [0] * 32, 1, '0x2f984bae4ddf95365ddd15ad7ad2c4a15769a136e0d2de26786b3f6f87329254'),
            ([3, 58], [12345, 53190], [0, 1, 255, 65535], 0, '0x53b79631e89490c4f6d3dfbd37c851086ee43eb262267c82e5b4af17f296ea40'),
            ([58], [65535], [65535] * 32, 2**64-1, '0x6798f90d351b321611e8f01817fac1be1bfff8989603098b3c08ab92150fc26c'),
        ]:
            self.assertEqual(generate_weight_hash(address=ALICE, netuid=2, uids=uids,
                values=values, salt=salt, version_key=version), expected)

    def test_rejects_invalid_commitment_inputs(self):
        valid = dict(address=ALICE, netuid=2, uids=[14], values=[65535], salt=[0]*32, version_key=1)
        for patch in [dict(netuid=-1), dict(uids=[65536]), dict(values=[True]),
                      dict(salt=[-1]), dict(version_key=2**64), dict(values=[])]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                generate_weight_hash(**(valid | patch))
