#!/usr/bin/env python3
"""
科研通(AbleSci)自动签到脚本
支持环境变量配置，可集成到定时任务（cron、青龙面板、GitHub Actions等）

环境变量：
  ABLESCI_AUTH     — 格式：邮箱#密码（兼容旧格式）
  ABLESCI_EMAIL    — 邮箱账号（与 ABLESCI_PASSWORD 配合使用）
  ABLESCI_PASSWORD — 密码

使用示例：
  export ABLESCI_EMAIL="your_email@qq.com"
  export ABLESCI_PASSWORD="your_password"
  python3 ablesci_sign.py

Author: WorkBuddy
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

# ======================== 配置区 ========================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Mobile Safari/537.36",
]

LOG_PATH = os.environ.get("ABLESCI_LOG_PATH", "ablesci_sign.log")

# ======================== 核心逻辑 ========================


def build_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.ablesci.com/",
        "X-Requested-With": "XMLHttpRequest",
    }


def extract_user_points(html: str) -> str:
    """从首页HTML中提取当前积分"""
    patterns = [
        r'id=["\']user-point-now["\'][^>]*>\s*([^<\s]+)\s*<',
        r'<[^>]+id=["\']user-point-now["\'][^>]*>\s*([^<]+?)\s*</[^>]+>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I | re.S)
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return ""


def fetch_user_points(opener) -> str:
    """获取当前积分"""
    home_req = Request("https://www.ablesci.com/", headers=build_headers())
    with opener.open(home_req, timeout=15) as resp:
        home_html = resp.read().decode("utf-8", errors="replace")
    return extract_user_points(home_html)


def extract_csrf(html: str) -> str:
    """从登录页面提取CSRF Token"""
    patterns = [
        r'<meta name="csrf-token" content="([^"]+)"',
        r'<input type="hidden" id="g_csrf_token" value="([^"]+)"',
        r'<input[^>]*name=["\']_csrf["\'][^>]*value=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1)
    raise ValueError("未找到 CSRF token")


def json_from_response(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"code": -1, "msg": "响应不是 JSON", "raw": raw[:300]}


def login_and_sign(email: str, password: str) -> dict:
    """
    完整签到流程：
    1. 获取登录页面 + CSRF Token
    2. 提交登录
    3. 获取签到前积分
    4. 执行签到
    5. 获取签到后积分
    """
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))

    # Step 1: 获取登录页面 + CSRF token
    req_home = Request("https://www.ablesci.com/site/login", headers=build_headers())
    with opener.open(req_home, timeout=15) as resp:
        login_html = resp.read().decode("utf-8", errors="replace")

    csrf = extract_csrf(login_html)
    time.sleep(random.uniform(0.8, 1.8))

    # Step 2: 提交登录
    post_data = urlencode(
        {
            "_csrf": csrf,
            "email": email,
            "password": password,
            "remember": "on",
        }
    ).encode("utf-8")

    login_headers = build_headers()
    login_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    login_headers["Referer"] = "https://www.ablesci.com/site/login"
    login_req = Request("https://www.ablesci.com/site/login", data=post_data, headers=login_headers)
    with opener.open(login_req, timeout=15) as resp:
        login_raw = resp.read().decode("utf-8", errors="replace")

    login_result = json_from_response(login_raw)
    if login_result.get("code") != 0:
        return login_result

    # Step 3: 获取签到前积分
    try:
        points_before = fetch_user_points(opener)
    except Exception:
        points_before = ""

    time.sleep(random.uniform(0.8, 1.8))

    # Step 4: 签到
    sign_req = Request("https://www.ablesci.com/user/sign", headers=build_headers())
    with opener.open(sign_req, timeout=15) as resp:
        sign_raw = resp.read().decode("utf-8", errors="replace")

    sign_result = json_from_response(sign_raw)

    # Step 5: 获取签到后积分
    try:
        points_after = fetch_user_points(opener)
    except Exception:
        points_after = ""

    sign_result["points_before"] = points_before
    sign_result["points_after"] = points_after
    return sign_result


def format_result(result: dict) -> str:
    """格式化签到结果用于输出"""
    msg = str(result.get("msg", ""))
    code = result.get("code")
    if code == 0:
        status = "✅ 签到成功"
    elif "已于" in msg and "签到" in msg:
        status = "⏰ 今日已签到"
    else:
        status = "❌ 签到失败"

    lines = [f"结果: {status}", f"消息: {msg}"]
    if result.get("points_before"):
        lines.append(f"签到前积分: {result['points_before']}")
    if result.get("points_after"):
        lines.append(f"签到后积分: {result['points_after']}")
    return "\n".join(lines)


def write_log(line: str) -> None:
    """追加写入日志"""
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    # 读取账号密码（支持两种环境变量格式）
    email = os.environ.get("ABLESCI_EMAIL", "").strip()
    password = os.environ.get("ABLESCI_PASSWORD", "").strip()

    if not email or not password:
        auth = os.environ.get("ABLESCI_AUTH", "").strip()
        if not auth or "#" not in auth:
            print("❌ 缺少环境变量！请设置 ABLESCI_EMAIL + ABLESCI_PASSWORD，或 ABLESCI_AUTH=邮箱#密码")
            sys.exit(1)
        email, password = auth.split("#", 1)
        email, password = email.strip(), password.strip()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 随机延迟（25%概率），避免被识别为机器人
    if random.random() < 0.25:
        delay = random.randint(10, 60)
        print(f"⏳ 随机延迟 {delay} 秒后执行...")
        time.sleep(delay)

    try:
        print(f"[{timestamp}] 开始签到，账号: {email[:3]}***{email.split('@')[1] if '@' in email else ''}")
        result = login_and_sign(email, password)

        output = format_result(result)
        print(output)

        log_line = f"[{timestamp}] code={result.get('code', -1)} msg={result.get('msg', '无消息')}"
        if result.get("points_before"):
            log_line += f" 签到前={result['points_before']}"
        if result.get("points_after"):
            log_line += f" 签到后={result['points_after']}"
        write_log(log_line)

    except Exception as exc:
        print(f"[{timestamp}] ❌ 异常: {exc}")
        write_log(f"[{timestamp}] ERROR {exc}")


if __name__ == "__main__":
    main()
