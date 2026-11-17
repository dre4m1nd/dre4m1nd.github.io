# tools/magpie_mcp.py
# magpie-image MCP 的轻量客户端（stdio JSON-RPC）
#
# 通过 MCP 协议调用本地 Magpie 的 image 服务（~/.pi/agent/mcp.json 里的 magpie-image），
# 用于生成博客封面。协议细节：
#   - 每行一个 JSON-RPC 消息，initialize -> notifications/initialized -> tools/call
#   - 通知（notifications/*）不带 id；请求才带 id，编号自增
#   - generate_image 若 20 秒内没完成，会返回一个 id，需再调 generation_result 轮询
#   - 服务端负责把图存到 path 指定的位置（绝对路径）

import json
import os
import subprocess
import time

EXE = r"D:\dev-environment\tool\magpie\magpie-windows-amd64.exe"
PROTOCOL = "2025-06-18"

DEFAULT_MODEL = "loomy/doubao-seedream-5-lite"  # 默认生图模型；OpenRouter/loomy-qwen 区域受限不可用

class MagpieImage:
    def __init__(self, exe=EXE):
        self.p = subprocess.Popen(
            [exe, "mcp", "image"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        self._id = 0
        self._init()

    def _send(self, obj):
        self._id += 1
        obj["id"] = self._id
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def _notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def _recv(self):
        while True:
            line = self.p.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def _init(self):
        self._send({"jsonrpc": "2.0", "method": "initialize",
                    "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                               "clientInfo": {"name": "covers", "version": "0.1"}}})
        r = self._recv()
        assert r and r.get("id") == self._id, "magpie-image 初始化失败: %s" % (r,)
        self._notify("notifications/initialized")

    def _call(self, name, arguments):
        self._send({"jsonrpc": "2.0", "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
        r = self._recv()
        if r is None or r.get("error"):
            raise RuntimeError("tools/call %s 失败: %s" % (name, r))
        texts = []
        for block in r["result"].get("content", []):
            if block.get("type") == "text":
                texts.append(block["text"])
        if r["result"].get("isError"):
            raise RuntimeError("magpie %s 报错: %s" % (name, " ".join(texts)[:300]))
        return " ".join(texts)


    def generate(self, prompt, path, model=None, size="1024x1024", max_wait=300):
        """生成图片到 path（绝对路径），返回实际落盘路径。

        默认 1024x1024：doubao 等模型对该尺寸最稳定，方形输出由封面脚本中心裁成 4:3。
        20 秒内没好就轮询 generation_result，直到文件出现或超时。
        """
        text = self._call("generate_image", {
            "prompt": prompt, "path": path, "size": size,
            **({"model": model} if model else {}),
        })
        if os.path.exists(path):
            return path
        for _ in range(max_wait // 5):
            time.sleep(5)
            if os.path.exists(path):
                return path
            # 服务端可能回复 id，也可能直接给文本，统一再问一次
            text = self._call("generation_result", {"id": text.strip()})
            if os.path.exists(path):
                return path
        raise RuntimeError("magpie 生成超时（%d 秒），未在 %s 落盘: %s" % (max_wait, path, text[:200]))

    def close(self):
        try:
            self.p.terminate()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
