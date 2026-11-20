#!/usr/bin/env python3
"""模型复读检测：流式输出时，如果结尾变成同一段文字首尾相接地重复，就立即中断生成。

思路学自 VibeSDK（它在流式输出里检测复读并立刻中止请求，省掉之后的 token）；实现是我们自己的“周期检测”：
每新到约 200 个字符检查一次——若输出结尾是某段长 p 的文字连续重复 R 次（R ≥ min_repeats，且总长 ≥ min_chars），
就判定为复读。只看结尾，所以前面正常的重复结构（列表、表格）不会误伤。
检查一次最多比较 (max_period − min_period) 个周期，每个周期最多比较 min_repeats × max_period 个字符，开销有上限。
"""


class RepeatGuard:
    def __init__(self, min_period=12, max_period=400, min_repeats=4, min_chars=200, check_every=200):
        self.min_p, self.max_p = min_period, max_period
        self.min_r, self.min_chars, self.every = min_repeats, min_chars, check_every
        self.buf = ""
        self.since = 0
        self.hit = None  # (周期长度, 重复次数, 重复的那段文字)

    def feed(self, chunk: str) -> bool:
        """喂进一段流式文本。返回 True 表示检测到复读，调用方应中断生成。"""
        if self.hit:
            return True
        self.buf += chunk
        self.since += len(chunk)
        if len(self.buf) > 20000:          # 只保留结尾，内存有界
            self.buf = self.buf[-8000:]
        if self.since >= self.every:
            self.since = 0
            self.hit = self._tail_period()
        return self.hit is not None

    def finish(self) -> bool:
        """流结束时再查一次（最后不足一个检查间隔的部分）。"""
        if not self.hit:
            self.hit = self._tail_period()
        return self.hit is not None

    def _tail_period(self):
        s = self.buf.rstrip()
        n = len(s)
        for p in range(self.min_p, min(self.max_p, n // self.min_r) + 1):
            unit = s[n - p:]
            if s[n - 2 * p:n - p] != unit:   # 先比一次，绝大多数周期在这里就排除
                continue
            r = 2
            while r * p + p <= n and s[n - (r + 1) * p:n - r * p] == unit:  # 有界：r 每次加一，最多 n/p 次
                r += 1
            if r >= self.min_r and r * p >= self.min_chars:
                return (p, r, unit)
        return None

    def describe(self) -> str:
        if not self.hit:
            return ""
        p, r, unit = self.hit
        return f"模型输出复读：同一段 {p} 个字符连续重复了 {r} 次（“{unit.strip()[:40]}…”），已中断生成"
