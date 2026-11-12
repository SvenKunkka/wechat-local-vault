"""Public NIST vector against the macOS system crypto provider."""
import sys
import unittest
from test_archive import GUARD_EVENTS
from wechat_vault.cipher import CommonCrypto


@unittest.skipUnless(sys.platform == "darwin", "Native CommonCrypto is macOS-only")
class NativeVectorCase(unittest.TestCase):
    def test_nist_aes256_cbc_vector(self):
        provider = CommonCrypto()
        key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plain = bytes.fromhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e5130c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710")
        encrypted = bytes.fromhex("f58c4c04d6e5f1ba779eabfb5f7bfbd69cfc4e967edb808d679f777bc6702c7d39f23369a9d9bacfa530e26304231461b2eb05e2c39be9fcda6c19078c6a9d1b")
        self.assertEqual(provider.decrypt(key, iv, encrypted), plain)
        self.assertEqual(provider.crypt(key, iv, plain, encrypt=True), encrypted)
        self.assertEqual(GUARD_EVENTS, [])
