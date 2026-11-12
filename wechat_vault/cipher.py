"""New SQLCipher4 page-profile implementation from public format interfaces."""
from __future__ import annotations
import ctypes
import hashlib
import hmac
import struct
import sys
from .errors import VaultError

PAGE = 4096
RESERVED = 80
USABLE = PAGE - RESERVED
PROFILE = "sqlcipher4-4096-raw"


class CommonCrypto:
    """Use the macOS system provider, without padding or custom AES code."""
    def __init__(self):
        if sys.platform != "darwin":
            raise VaultError("Native decryption requires macOS CommonCrypto; nothing was installed.")
        try:
            self.library = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")
            self.call = self.library.CCCrypt
            self.call.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
            self.call.restype = ctypes.c_int32
        except (OSError, AttributeError):
            raise VaultError("The macOS system AES provider is unavailable.") from None

    def crypt(self, key, iv, payload, *, encrypt=False):
        if len(key) != 32 or len(iv) != 16 or not payload or len(payload) % 16:
            raise VaultError("Invalid AES-256-CBC input size.")
        key_buffer = ctypes.create_string_buffer(key, len(key))
        iv_buffer = ctypes.create_string_buffer(iv, len(iv))
        input_buffer = ctypes.create_string_buffer(payload, len(payload))
        output_buffer = ctypes.create_string_buffer(len(payload))
        written = ctypes.c_size_t()
        try:
            status = self.call(0 if encrypt else 1, 0, 0, key_buffer, 32, iv_buffer,
                               input_buffer, len(payload), output_buffer, len(payload), ctypes.byref(written))
            if status != 0 or written.value != len(payload):
                raise VaultError("The system AES operation failed.")
            return output_buffer.raw
        finally:
            for buffer in (key_buffer, iv_buffer, input_buffer, output_buffer):
                ctypes.memset(ctypes.addressof(buffer), 0, ctypes.sizeof(buffer))
            # Python bytes and provider-internal copies cannot be reliably erased.

    def decrypt(self, key, iv, payload):
        return self.crypt(key, iv, payload)


class PageDecoder:
    def __init__(self, key, salt, provider):
        if len(key) != 32 or len(salt) != 16:
            raise VaultError("The selected cipher profile requires a 32-byte raw key.")
        self.key, self.salt, self.provider = key, salt, provider
        self.auth_key = hashlib.pbkdf2_hmac("sha512", key, bytes(value ^ 0x3a for value in salt), 2, 32)

    def authenticate(self, page, number):
        if len(page) != PAGE or not 1 <= number <= 0xffffffff:
            raise VaultError("Invalid encrypted page layout.")
        start = 16 if number == 1 else 0
        if number == 1 and page[:16] != self.salt:
            raise VaultError("Database salt changed; no output was published.")
        expected = hmac.digest(self.auth_key, page[start:USABLE + 16] + struct.pack("<I", number), "sha512")
        if not hmac.compare_digest(expected, page[USABLE + 16:]):
            raise VaultError("Page authentication failed; check the key and source integrity.")

    def decode(self, page, number):
        self.authenticate(page, number)
        start = 16 if number == 1 else 0
        plain = self.provider.decrypt(self.key, page[USABLE:USABLE + 16], page[start:USABLE])
        result = (b"SQLite format 3\0" if number == 1 else b"") + plain + bytes(RESERVED)
        if number == 1:
            if result[16:18] != struct.pack(">H", PAGE) or result[20] != RESERVED or result[21:24] != bytes((64, 32, 32)):
                raise VaultError("Authenticated page uses an unsupported SQLite layout.")
            result = bytearray(result)
            result[18:20] = b"\1\1"  # Reconstructed standalone snapshot uses rollback mode, not WAL.
            result = bytes(result)
        return result
