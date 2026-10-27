"""The runtime's SCALE weight commitment; no HTTP framework or SDK dependency."""
import hashlib

from bittensor_wallet import Keypair


def unsigned(value, width):
    if type(value) is not int or not 0 <= value < 1 << (width * 8):
        raise ValueError('Weight commitment integer is out of range')
    return value.to_bytes(width, 'little')


def compact(value):
    # Subnet vectors are bounded well below SCALE's large-integer mode.
    if value < 64:
        return bytes([value << 2])
    if value < 16384:
        return ((value << 2) | 1).to_bytes(2, 'little')
    raise ValueError('Weight commitment vector is too large')


def vector(values):
    return compact(len(values)) + b''.join(unsigned(value, 2) for value in values)


def generate_weight_hash(*, address, netuid, uids, values, salt, version_key):
    if len(uids) != len(values):
        raise ValueError('Weight UIDs and values differ in length')
    public = bytes(Keypair(ss58_address=address).public_key)
    if len(public) != 32:
        raise ValueError('Weight account must be AccountId32')
    encoded = (public + unsigned(netuid, 2) + vector(uids) + vector(values)
               + vector(salt) + unsigned(version_key, 8))
    return '0x' + hashlib.blake2b(encoded, digest_size=32).hexdigest()
