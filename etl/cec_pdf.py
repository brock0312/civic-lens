"""中選會 Excel／Word 轉出的表格 PDF：依 pdftotext -bbox 的字詞座標切格（V11 §1.3）。

儲存格文字垂直置中，所以同一欄的連續行切成幾段、依序分給各列，
取「每段中心與列中心偏差總和最小」的切法；正確切法的偏差都在 3pt 以內。
"""
import html
import re
import subprocess

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
MAX_OFFSET = 3


def bbox_html(pdf_bytes):
    return subprocess.run(
        ["pdftotext", "-bbox", "-", "-"], input=pdf_bytes, capture_output=True, check=True
    ).stdout.decode("utf-8")


def pages(bbox):
    """bbox HTML → 每頁一個 [(x0, y0, x1, y1, text)]。"""
    return [
        [(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in WORD.findall(p)]
        for p in re.findall(r"<page.*?</page>", bbox, re.S)
    ]


def group_lines(words):
    """同一欄的字依 y0 併成行：{y0: [(x0, x1, text, y1)]}。"""
    lines = {}
    for x0, y0, x1, y1, t in words:
        lines.setdefault(round(y0, 1), []).append((x0, x1, t, y1))
    return {y: sorted(ws) for y, ws in lines.items()}


def line_text(ws):
    """一行內的字詞：中間有間隙（原文有空白）就補一個半形空白，否則直接相連。"""
    out, prev_x1 = "", None
    for x0, x1, t, _ in ws:
        if prev_x1 is not None and x0 - prev_x1 > 1:
            out += " "
        out += t
        prev_x1 = x1
    return out


def assign(ys, lines, row_centers, optional, loose_last=False):
    """把排序好的行 ys 切成連續段，依序指派給各列（DP）。

    optional：該欄可以空白（例如備註）。loose_last：頁面最後一列可能跨頁，只要求起點不在列中心之下。
    偏差超過 MAX_OFFSET 就 raise ValueError。
    """
    inf = float("inf")
    n_lines, n_rows = len(ys), len(row_centers)

    def center(a, b):
        return (ys[a] + lines[ys[b - 1]][0][3]) / 2

    dp = [[inf] * (n_lines + 1) for _ in range(n_rows + 1)]
    back = [[None] * (n_lines + 1) for _ in range(n_rows + 1)]
    dp[0][0] = 0
    for j in range(1, n_rows + 1):
        for i in range(n_lines + 1):
            for k in range(i + 1):
                if (k == i and not optional) or dp[j - 1][k] == inf:
                    continue
                cost = 0 if k == i else abs(center(k, i) - row_centers[j - 1])
                if loose_last and j == n_rows and k < i and ys[k] - row_centers[j - 1] < MAX_OFFSET:
                    cost = 0
                if dp[j - 1][k] + cost < dp[j][i]:
                    dp[j][i], back[j][i] = dp[j - 1][k] + cost, k
    if dp[n_rows][n_lines] == inf:
        raise ValueError("無法把行分配給列")
    out, i = [], n_lines
    for j in range(n_rows, 0, -1):
        k = back[j][i]
        if k != i and not (loose_last and j == n_rows):
            off = center(k, i) - row_centers[j - 1]
            if abs(off) > MAX_OFFSET:
                raise ValueError(f"儲存格中心偏離列中心 {off:.1f}pt：{ys[k:i]}")
        out.append(ys[k:i])
        i = k
    return out[::-1]
