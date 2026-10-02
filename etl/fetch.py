import http.client
import json
import socket
import subprocess
import urllib.request
from datetime import datetime, timezone

UA = "civic-lens-etl/0.1"


def _connect_v4(address, timeout, source_address=None):
    host, port = address
    ip = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    return socket.create_connection((ip, port), timeout, source_address)


class _V4Connection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_v4  # TLS 的 SNI 與憑證檢查仍用原主機名


class _V4Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_V4Connection, req, context=self._context)


_V4_OPENER = urllib.request.build_opener(_V4Handler)


# ponytail: 不做重試；失敗就 raise，每日排程明天會再跑
def get(url, ipv4=False):
    """ipv4=True 只連 IPv4：有些主機公告了 IPv6 位址但連不上，urllib 會先等 60 秒逾時才改連 IPv4。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with (_V4_OPENER.open if ipv4 else urllib.request.urlopen)(req, timeout=60) as resp:  # HTTP 錯誤會 raise HTTPError
        return resp.read()


def get_json(url):
    return json.loads(get(url))


def pdf_text(data):
    return subprocess.run(
        ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
    ).stdout.decode("utf-8")


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
