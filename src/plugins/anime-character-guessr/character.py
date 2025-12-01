import logging
from Crypto.Cipher import AES
from Crypto.Hash import MD5
from base64 import b64decode
import json
from typing import Optional

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16):
    """
    模拟 CryptoJS 的 EVP_BytesToKey，用于从 password 和 salt 生成 key 和 iv
    """
    d = b''
    last = b''
    while len(d) < (key_len + iv_len):
        last = MD5.new(last + password + salt).digest()
        d += last
    return d[:key_len], d[key_len:key_len+iv_len]

def decrypt_character_js_style(encrypted_data: str, secret_key: str = "xmb1236987") -> Optional[dict]:
    try:
        encrypted_bytes = b64decode(encrypted_data)
        logger.debug(f"Encrypted bytes: {encrypted_bytes}")

        if not encrypted_bytes.startswith(b"Salted__"):
            raise ValueError("密文缺少 CryptoJS 标准 Salted__ 前缀")

        salt = encrypted_bytes[8:16]
        cipher_text = encrypted_bytes[16:]

        key, iv = evp_bytes_to_key(secret_key.encode('utf-8'), salt)

        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(cipher_text)

        # 去除 PKCS7 padding
        pad_len = decrypted[-1]
        if pad_len < 1 or pad_len > 16:
            raise ValueError("非法填充长度")
        decrypted = decrypted[:-pad_len]

        decrypted_text = decrypted.decode("utf-8")
        logger.debug(f"Decrypted text: {decrypted_text}")

        return json.loads(decrypted_text)

    except Exception as e:
        logger.error(f"解密失败: {e}")
        return None
