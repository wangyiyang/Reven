"""通过飞书应用机器人发送部署结果，凭证只从 Actions 环境变量读取。"""

import json
import os
import re
import sys
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

API_BASE = "https://open.feishu.cn/open-apis"
CONFIG_KEYS = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_NOTIFY_OPEN_IDS")


def post(path: str, payload: dict[str, object], token: str | None = None) -> dict[str, object]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(API_BASE + path, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"飞书通知请求失败（HTTP {exc.code}）") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("飞书通知请求网络失败") from None
    except (ValueError, UnicodeError):
        raise RuntimeError("飞书通知响应格式无效") from None
    if not isinstance(result, dict):
        raise RuntimeError("飞书通知响应格式无效")
    code = result.get("code")
    if type(code) is not int:
        raise RuntimeError("飞书通知响应格式无效（invalid_response）")
    if code != 0:
        raise RuntimeError(f"飞书通知请求失败（code={code}）")
    return result


def send_notification(environment: Mapping[str, str]) -> int:
    values = [environment.get(key, "").strip() for key in CONFIG_KEYS]
    if not any(values):
        print("未配置飞书应用部署通知，跳过。")
        return 0
    if not all(values):
        raise ValueError("飞书部署通知配置不完整：需同时配置 FEISHU_APP_ID、FEISHU_APP_SECRET、FEISHU_NOTIFY_OPEN_IDS")
    app_id, app_secret, raw_recipients = values
    recipients = list(dict.fromkeys(re.split(r"[\s,，]+", raw_recipients)))
    if not recipients or any(not re.fullmatch(r"ou_[A-Za-z0-9]+", value) for value in recipients):
        raise ValueError("FEISHU_NOTIFY_OPEN_IDS 必须为应用下的用户 Open ID，使用逗号或空白分隔")
    authentication = post("/auth/v3/tenant_access_token/internal", {"app_id": app_id, "app_secret": app_secret})
    token = authentication.get("tenant_access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("飞书应用未返回有效访问令牌")
    text = _message(environment)
    run_key = f"{environment.get('GITHUB_RUN_ID', '')}:{environment.get('GITHUB_RUN_ATTEMPT', '')}"
    for recipient in recipients:
        post(
            "/im/v1/messages?receive_id_type=open_id",
            {
                "receive_id": recipient,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "uuid": str(uuid5(NAMESPACE_URL, f"{run_key}:{recipient}:{text}")),
            },
            token,
        )
    print(f"飞书应用部署通知已发送给 {len(recipients)} 位接收人。")
    return 0


def _message(environment: Mapping[str, str]) -> str:
    status = environment.get("JOB_STATUS", "unknown")
    image = environment.get("DEPLOY_IMAGE", "previous healthy image")
    server = environment.get("GITHUB_SERVER_URL", "https://github.com")
    repository = environment.get("GITHUB_REPOSITORY", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    return f"Reven production {status}: {image}\n{server}/{repository}/actions/runs/{run_id}"


def main() -> int:
    try:
        return send_notification(os.environ)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
