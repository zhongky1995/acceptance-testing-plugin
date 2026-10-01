"""Disposable localhost UI for validating browser evidence, standard library."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from app import approve, create_request

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>审批验收样例</title>
<style>body{font:18px system-ui;max-width:720px;margin:70px auto;padding:24px}button,input,select{font:inherit;padding:10px;margin:8px}#result{padding:18px;background:#edf2f7;white-space:pre-wrap}label{display:block}</style>
<h1>审批验收样例</h1><p>本地隔离数据，不连接真实业务。</p>
<label>申请人 <input id="requester" value="alice"></label>
<label>审批人 <input id="actor" value="alice"></label>
<label>角色 <select id="role"><option value="manager">主管</option><option value="employee">员工</option></select></label>
<button id="approve">审批申请</button><pre id="result">尚未操作</pre>
<script>document.querySelector('#approve').onclick=async()=>{let p={requester:document.querySelector('#requester').value,actor:document.querySelector('#actor').value,role:document.querySelector('#role').value};let r=await fetch('/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});let d=await r.json();document.querySelector('#result').textContent=JSON.stringify(d,null,2)}</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/approve":
            self.send_error(404)
            return
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            req = create_request(data["requester"], 500)
            approve(req, data["actor"], data["role"])
            body, code = {"status": "approved", "request": req}, 200
        except PermissionError as exc:
            body, code = {"status": "denied", "reason": str(exc)}, 403
        except (ValueError, KeyError):
            body, code = {"status": "invalid"}, 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()
