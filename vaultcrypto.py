"""密钥管理、内容加密与盲索引。

安全模型
--------
1. 主密钥（32 字节随机数）保存在本机应用数据目录的 key.bin。
   在 Windows 上，密钥文件本身再用 DPAPI 加密，只有当前登录用户能解开；
   换用户、换机器或把文件拷走都无法还原。
2. 每条剪贴板内容用 Fernet 加密后以 BLOB 落库。
   Fernet = AES-128-CBC + HMAC-SHA256 + 随机 IV，自带完整性校验。
3. 去重需要一个「能比较但不可逆」的键，因此使用 HMAC 盲索引：
   - 用主密钥派生一把独立的索引密钥，避免与加密密钥混用；
   - 对内容做 HMAC-SHA256 得到十六进制串；
   - 攻击者拿到数据库也无法用字典反推原文（没有密钥算不出 HMAC）。
4. 敏感内容的临时暂存区使用 SessionCipher：密钥只存在内存里，进程退出即失效。

为什么不直接用明文 SHA-256 当去重键？
    因为「你复制过某个密码」本身也是信息，字典攻击可以直接撞库。
    HMAC 必须持有密钥才能计算，泄露数据库不等于泄露可验证的指纹。
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

_MAGIC_DPAPI = b"CVDP1"
_MAGIC_RAW = b"CVRW1"


def _dpapi(data: bytes, protect: bool) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.c_uint32),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
    if not ok:
        raise OSError("DPAPI 调用失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def load_or_create_master_key(path: Path) -> bytes:
    if path.exists():
        blob = path.read_bytes()
        if blob.startswith(_MAGIC_DPAPI):
            if sys.platform != "win32":
                raise RuntimeError("密钥由 Windows DPAPI 保护，无法在当前系统读取")
            raw = _dpapi(blob[len(_MAGIC_DPAPI):], protect=False)
        elif blob.startswith(_MAGIC_RAW):
            raw = blob[len(_MAGIC_RAW):]
        else:
            raw = blob
        if len(raw) != 32:
            raise RuntimeError("密钥文件已损坏")
        return raw

    raw = os.urandom(32)
    if sys.platform == "win32":
        payload = _MAGIC_DPAPI + _dpapi(raw, protect=True)
    else:
        payload = _MAGIC_RAW + raw
    path.write_bytes(payload)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return raw


class VaultCrypto:
    """持久化内容的加解密与盲索引。"""

    def __init__(self, master: bytes) -> None:
        self._fernet = Fernet(base64.urlsafe_b64encode(master))
        self._index_key = hmac.new(master, b"gluepaw-blind-v1", hashlib.sha256).digest()

    def encrypt(self, text: str) -> bytes:
        return self._fernet.encrypt(text.encode("utf-8"))

    def decrypt(self, blob: bytes) -> str:
        return self._fernet.decrypt(bytes(blob)).decode("utf-8")

    def blind(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        return hmac.new(self._index_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


class SessionCipher:
    """只在内存中使用的会话密钥，进程退出即失效。"""

    def __init__(self) -> None:
        self._fernet = Fernet(Fernet.generate_key())

    def encrypt(self, text: str) -> bytes:
        return self._fernet.encrypt(text.encode("utf-8"))

    def decrypt(self, blob: bytes) -> str:
        return self._fernet.decrypt(bytes(blob)).decode("utf-8")
