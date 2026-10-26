"""ASCII armor for verified Fedora public keys consumed by native RPM."""

import base64


def armor_public_key(raw):
    # RPM4's public-key parser requires ASCII armor including its legacy CRC24.
    crc = 0xB704CE
    for value in raw:
        crc ^= value << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    checksum = base64.b64encode((crc & 0xFFFFFF).to_bytes(3, 'big'))
    return (b'-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n' + base64.encodebytes(raw) +
            b'=' + checksum + b'\n-----END PGP PUBLIC KEY BLOCK-----\n')
