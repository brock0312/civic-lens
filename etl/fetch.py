import json
import subprocess
import urllib.request
from datetime import datetime, timezone

UA = "civic-lens-etl/0.1"


# ponytail: 不做重試；失敗就 raise，每日排程明天會再跑
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:  # HTTP 錯誤會 raise HTTPError
        return resp.read()


def get_json(url):
    return json.loads(get(url))


def pdf_text(data):
    return subprocess.run(
        ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
    ).stdout.decode("utf-8")


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
