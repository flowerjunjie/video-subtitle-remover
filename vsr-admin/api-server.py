"""
VSR 激活码 API 服务
运行在服务器上，提供激活码管理 REST API
支持管理员密码 + 服务端实时验证
"""
import json
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify
from werkzeug.serving import make_server

app = Flask(__name__)

# 激活码数据文件路径
ACTIVATION_FILE = "/var/www/vsr-data/activation_codes.json"
os.makedirs("/var/www/vsr-data", exist_ok=True)

# 管理员密码 (默认: admin123，线上请修改环境变量)
ADMIN_PASSWORD = os.environ.get("VSR_ADMIN_PASSWORD", "admin123")
ADMIN_PASSWORD_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()

# Session token storage (简单实现，内存存储，生产环境用 Redis)
SESSIONS = {}


def require_admin(f):
    """管理员权限校验装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token or SESSIONS.get(token) != ADMIN_PASSWORD_HASH:
            return jsonify({"error": "未授权"}), 401
        return f(*args, **kwargs)
    return decorated


def load_data():
    """加载激活码数据"""
    if os.path.exists(ACTIVATION_FILE):
        with open(ACTIVATION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"codes": []}


def save_data(data):
    """保存激活码数据"""
    with open(ACTIVATION_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_stats():
    """获取统计数据"""
    data = load_data()
    codes = data.get("codes", [])
    total = len(codes)
    unused = sum(1 for c in codes if c["status"] == "unused")
    active = sum(1 for c in codes if c["status"] == "active")
    expired = sum(1 for c in codes if c["status"] == "expired")
    total_revenue = sum(c.get("price", 0) for c in codes if c["status"] in ("active", "expired"))

    # 清理过期
    now = datetime.now()
    for i, entry in enumerate(codes):
        if entry["status"] == "active" and entry.get("expires_at"):
            try:
                expiry = datetime.fromisoformat(entry["expires_at"])
                if expiry < now:
                    codes[i]["status"] = "expired"
            except Exception:
                pass

    save_data({"codes": codes})

    return {
        "total": total,
        "unused": unused,
        "active": active,
        "expired": expired,
        "total_revenue": round(total_revenue, 2)
    }


# ===== 管理员登录 =====

@app.route('/api/admin/login', methods=['POST'])
def api_login():
    """管理员登录"""
    body = request.get_json() or {}
    password = body.get('password', '')

    if hashlib.sha256(password.encode()).hexdigest() != ADMIN_PASSWORD_HASH:
        return jsonify({"error": "密码错误"}), 401

    # 生成 session token
    token = secrets.token_hex(32)
    SESSIONS[token] = ADMIN_PASSWORD_HASH
    return jsonify({"token": token})


# ===== 激活码管理 (需登录) =====

@app.route('/api/stats', methods=['GET'])
@require_admin
def api_stats():
    """获取统计数据"""
    return jsonify(get_stats())


@app.route('/api/codes', methods=['GET'])
@require_admin
def api_list():
    """获取激活码列表"""
    status_filter = request.args.get('status', 'all')
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 20))

    data = load_data()
    codes = data.get("codes", [])

    # 筛选
    if status_filter != 'all':
        codes = [c for c in codes if c["status"] == status_filter]

    codes.reverse()
    total = len(codes)
    total_pages = max(1, (total + page_size - 1) // page_size)

    start = (page - 1) * page_size
    end = start + page_size
    page_codes = codes[start:end]

    return jsonify({
        "codes": page_codes,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    })


@app.route('/api/codes', methods=['POST'])
@require_admin
def api_create():
    """生成激活码"""
    body = request.get_json()
    count = body.get('count', 1)
    months = body.get('months', 1)

    data = load_data()
    entries = []

    for _ in range(count):
        random_part = secrets.token_hex(16).upper()
        code = f"VSR-{random_part[:4]}-{random_part[4:8]}-{random_part[8:12]}-{random_part[12:16]}"

        entry = {
            "code": code,
            "months": months,
            "price": round(9.9 * months, 2),
            "created_at": datetime.now().isoformat(),
            "activated_at": None,
            "expires_at": None,
            "machine_id": None,
            "status": "unused"
        }
        entries.append(entry)
        data["codes"].append(entry)

    save_data(data)

    return jsonify({
        "success": True,
        "codes": entries,
        "count": len(entries)
    })


@app.route('/api/codes/<code>', methods=['DELETE'])
@require_admin
def api_delete(code):
    """删除激活码"""
    data = load_data()
    original_len = len(data["codes"])
    data["codes"] = [c for c in data["codes"] if c["code"] != code]

    if len(data["codes"]) == original_len:
        return jsonify({"success": False, "message": "激活码不存在"}), 404

    save_data(data)
    return jsonify({"success": True, "message": "删除成功"})


@app.route('/api/codes/activate', methods=['POST'])
def api_activate():
    """激活码激活（客户端调用）"""
    body = request.get_json()
    code = body.get('code', '').strip()
    machine_id = body.get('machine_id', '')

    if not code or not machine_id:
        return jsonify({"success": False, "message": "参数不完整"}), 400

    data = load_data()
    found_entry = None
    found_index = -1

    for i, entry in enumerate(data["codes"]):
        if entry["code"] == code:
            found_entry = entry
            found_index = i
            break

    if not found_entry:
        return jsonify({"success": False, "message": "激活码无效"}), 400

    if found_entry["status"] == "active":
        return jsonify({"success": False, "message": "该激活码已被使用"}), 400

    if found_entry["status"] == "expired":
        return jsonify({"success": False, "message": "该激活码已过期"}), 400

    # 执行激活
    now = datetime.now()
    expires_at = now + timedelta(days=found_entry["months"] * 30)

    data["codes"][found_index]["activated_at"] = now.isoformat()
    data["codes"][found_index]["expires_at"] = expires_at.isoformat()
    data["codes"][found_index]["machine_id"] = machine_id
    data["codes"][found_index]["status"] = "active"

    save_data(data)

    return jsonify({
        "success": True,
        "message": "激活成功",
        "expires_at": expires_at.isoformat(),
        "months": found_entry["months"]
    })


@app.route('/api/codes/verify', methods=['POST'])
def api_verify():
    """
    实时验证激活状态（客户端每次启动调用）
    返回：是否有效 + 剩余天数 + 到期日
    """
    body = request.get_json()
    machine_id = body.get('machine_id', '')

    if not machine_id:
        return jsonify({"success": False, "message": "缺少机器ID"}), 400

    data = load_data()
    now = datetime.now()

    # 查找该机器ID对应的激活码
    for entry in data["codes"]:
        if entry.get("machine_id") == machine_id and entry["status"] == "active":
            # 检查是否过期
            if entry.get("expires_at"):
                try:
                    expiry = datetime.fromisoformat(entry["expires_at"])
                    remaining = (expiry - now).days
                    if remaining < 0:
                        return jsonify({
                            "valid": False,
                            "message": "授权已过期",
                            "expires_at": entry["expires_at"],
                            "days_remaining": 0
                        })
                    return jsonify({
                        "valid": True,
                        "message": "授权有效",
                        "expires_at": entry["expires_at"],
                        "days_remaining": remaining,
                        "code": entry["code"],
                        "months": entry["months"]
                    })
                except Exception:
                    pass

    return jsonify({
        "valid": False,
        "message": "未找到有效授权",
        "days_remaining": 0
    })


@app.route('/api/health', methods=['GET'])
def api_health():
    """健康检查"""
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


if __name__ == '__main__':
    port = 8099
    print(f"VSR API Server starting on port {port}...")
    print(f"Admin password: {ADMIN_PASSWORD} (change via VSR_ADMIN_PASSWORD env)")
    app.run(host='0.0.0.0', port=port, debug=False)