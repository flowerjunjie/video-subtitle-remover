"""
激活码系统 - 核心模块
功能：激活码生成、校验、续期管理
"""
import hashlib
import json
import os
import secrets
import uuid
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# ========== 常量 ==========
PRICE_PER_MONTH = 9.9  # 元/月
ACTIVATION_CODE_PREFIX = "VSR"
ACTIVATION_FILE = "config/activation_codes.json"
STATUS_FILE = "config/activation_status.json"
SALT = "vsr2024activation_salt_key"  # 生产环境应更换为更复杂的盐值


def get_machine_id() -> str:
    """获取机器唯一标识（基于CPU+主板+磁盘）"""
    import platform
    import socket

    raw = (
        platform.node() +
        platform.machine() +
        platform.processor() +
        socket.gethostname()
    ).encode()

    return hashlib.md5(raw).hexdigest().upper()


def generate_activation_code(months: int = 1) -> str:
    """
    生成激活码
    格式: VSR-XXXX-XXXX-XXXX-XXXX (19字符)
    激活码本身为随机字符串，月数信息存储在数据库中
    """
    random_part = secrets.token_hex(16).upper()  # 32 hex chars

    # 取前16个字符，格式化为 VSR-XXXX-XXXX-XXXX-XXXX
    code = f"{ACTIVATION_CODE_PREFIX}-{random_part[:4]}-{random_part[4:8]}-{random_part[8:12]}-{random_part[12:16]}"
    return code


def verify_activation_code(code: str) -> Tuple[bool, Optional[Dict]]:
    """
    校验激活码格式和有效性
    格式: VSR-XXXX-XXXX-XXXX-XXXX (23字符)
    返回：(是否有效, 解析出的信息字典)
    """
    if not code or len(code) != 23:
        return False, None

    try:
        parts = code.split("-")
        if len(parts) != 5 or parts[0] != ACTIVATION_CODE_PREFIX:
            return False, None

        raw = code.replace(f"{ACTIVATION_CODE_PREFIX}-", "").replace("-", "")
        if len(raw) < 16:
            return False, None

        return True, {"code": code, "raw": raw}
    except Exception:
        return False, None


def calculate_expiry_date(activated_at: datetime, months: int) -> datetime:
    """计算到期日"""
    return activated_at + timedelta(days=months * 30)


def load_activation_codes() -> Dict:
    """加载激活码数据库"""
    path = Path(ACTIVATION_FILE)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"codes": []}


def save_activation_codes(data: Dict) -> None:
    """保存激活码数据库"""
    path = Path(ACTIVATION_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_activation_code_entry(months: int = 1) -> Dict:
    """创建单个激活码条目"""
    code = generate_activation_code(months)
    entry = {
        "code": code,
        "months": months,
        "price": round(PRICE_PER_MONTH * months, 2),
        "created_at": datetime.now().isoformat(),
        "activated_at": None,
        "expires_at": None,
        "machine_id": None,
        "status": "unused"  # unused / active / expired
    }
    return entry


def generate_batch_codes(count: int, months: int = 1) -> List[Dict]:
    """批量生成激活码"""
    entries = []
    codes_data = load_activation_codes()

    for _ in range(count):
        entry = create_activation_code_entry(months)
        entries.append(entry)
        codes_data["codes"].append(entry)

    save_activation_codes(codes_data)
    return entries


def activate_code(code: str, machine_id: str = None) -> Tuple[bool, str, Optional[Dict]]:
    """
    激活码激活
    返回：(是否成功, 消息, 激活信息字典)
    """
    if machine_id is None:
        machine_id = get_machine_id()

    codes_data = load_activation_codes()

    # 查找激活码
    found_entry = None
    found_index = -1
    for i, entry in enumerate(codes_data["codes"]):
        if entry["code"] == code:
            found_entry = entry
            found_index = i
            break

    if found_entry is None:
        return False, "激活码无效", None

    if found_entry["status"] == "active":
        return False, "该激活码已被使用", None

    if found_entry["status"] == "expired":
        return False, "该激活码已过期", None

    # 激活
    now = datetime.now()
    found_entry["activated_at"] = now.isoformat()
    found_entry["expires_at"] = calculate_expiry_date(now, found_entry["months"]).isoformat()
    found_entry["machine_id"] = machine_id
    found_entry["status"] = "active"

    codes_data["codes"][found_index] = found_entry
    save_activation_codes(codes_data)

    # 保存本地激活状态
    save_activation_status({
        "activated": True,
        "code": code,
        "machine_id": machine_id,
        "activated_at": found_entry["activated_at"],
        "expires_at": found_entry["expires_at"],
        "months": found_entry["months"],
        "days_remaining": found_entry["months"] * 30
    })

    return True, "激活成功", found_entry


def save_activation_status(status: Dict) -> None:
    """保存本地激活状态"""
    path = Path(STATUS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def load_activation_status() -> Dict:
    """加载本地激活状态"""
    path = Path(STATUS_FILE)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"activated": False}


def check_activation_status() -> Tuple[bool, int]:
    """
    检查激活状态
    返回：(是否激活且未过期, 剩余天数)
    """
    status = load_activation_status()

    if not status.get("activated"):
        return False, 0

    expires_at = status.get("expires_at")
    if not expires_at:
        return False, 0

    try:
        expiry = datetime.fromisoformat(expires_at)
        now = datetime.now()
        remaining = (expiry - now).days

        if remaining < 0:
            return False, 0
        return True, remaining
    except Exception:
        return False, 0


def delete_activation_code(code: str) -> Tuple[bool, str]:
    """删除激活码"""
    codes_data = load_activation_codes()

    new_codes = [c for c in codes_data["codes"] if c["code"] != code]
    if len(new_codes) == len(codes_data["codes"]):
        return False, "激活码不存在"

    codes_data["codes"] = new_codes
    save_activation_codes(codes_data)
    return True, "删除成功"


def get_all_codes() -> List[Dict]:
    """获取所有激活码"""
    codes_data = load_activation_codes()
    return codes_data.get("codes", [])


def get_code_stats() -> Dict:
    """获取激活码统计"""
    codes = get_all_codes()
    total = len(codes)
    unused = sum(1 for c in codes if c["status"] == "unused")
    active = sum(1 for c in codes if c["status"] == "active")
    expired = sum(1 for c in codes if c["status"] == "expired")
    total_revenue = sum(c.get("price", 0) for c in codes if c["status"] in ("active", "expired"))

    return {
        "total": total,
        "unused": unused,
        "active": active,
        "expired": expired,
        "total_revenue": round(total_revenue, 2)
    }


def cleanup_expired_codes() -> int:
    """清理过期激活码，返回清理数量"""
    codes_data = load_activation_codes()
    now = datetime.now()
    cleaned = 0

    for i, entry in enumerate(codes_data["codes"]):
        if entry["status"] == "active" and entry.get("expires_at"):
            try:
                expiry = datetime.fromisoformat(entry["expires_at"])
                if expiry < now:
                    codes_data["codes"][i]["status"] = "expired"
                    cleaned += 1
            except Exception:
                pass

    if cleaned > 0:
        save_activation_codes(codes_data)

    return cleaned