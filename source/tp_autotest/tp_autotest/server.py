import argparse
import json
import os
import sys
import threading
import time
import base64
import iperf3
import subprocess
import asyncio
import websockets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer
from .utils.serial_utils import SerialServer
class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)


class HttpServer(BaseHTTPRequestHandler):
    server_version = "AutoTestSerialMonitor/1.0"
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Allow', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-control-allow-headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        base_dir = os.path.dirname(os.path.abspath(__file__))

        if parsed.path in ('/', '/index.html', '/serial_monitor.html'):
            try:
                html_file_path = os.path.join(base_dir, 'page', 'serial_monitor', 'serial_monitor.html')
                with open(html_file_path, 'r', encoding='utf-8') as f:
                    self._send_html(f.read())
            except FileNotFoundError:
                self.send_error(404, 'Not Found')
            return
        elif parsed.path.startswith('/static/'):
            relative_path = parsed.path.lstrip('/')
            file_path = os.path.join(base_dir, 'page', 'serial_monitor', relative_path)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        self.send_response(200)
                        if file_path.endswith('.css'):
                            self.send_header('Content-Type', 'text/css')
                        elif file_path.endswith('.js'):
                            self.send_header('Content-Type', 'application/javascript')
                        else:
                            self.send_header('Content-Type', 'application/octet-stream')
                        self.end_headers()
                        self.wfile.write(f.read())
                except Exception as e:
                    self.send_error(500, f'Error serving file: {e}')
            else:
                self.send_error(404, 'File Not Found')
            return
        self.send_error(404, 'Not Found')

    def _send_html(self, html):
        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(data)


class WebsocketServer:
    def __init__(self, host, port, serial_server: SerialServer):
        self.host = host
        self.port = port
        self.serial_server = serial_server
        self.loop = None
        self.server = None
        self.clients = set()
        # Register self as a listener to the serial_server
        self.serial_server.register_listener(self.serial_event_handler)

    def serial_event_handler(self, event, payload):
        """Handles events from SerialServer and broadcasts them to clients."""
        if not self.loop:
            return
        
        message = json.dumps({"type": event, "payload": payload})
        
        # This handler might be called from a different thread (e.g., RPC thread).
        # We need to schedule the broadcast on the asyncio event loop safely.
        self.loop.call_soon_threadsafe(asyncio.create_task, self.broadcast(message))

    async def broadcast(self, message):
        """Broadcasts a message to all connected clients."""
        if self.clients:
            await asyncio.gather(*[client.send(message) for client in self.clients])

    async def _handler(self, websocket):
        self.clients.add(websocket)
        subscriptions = {}  # port -> { "queue": Queue, "task": Task }

        async def forward_task(port, queue):
            while True:
                try:
                    data = await asyncio.to_thread(queue.get, timeout=1.0)
                    if data:
                        encoded_data = base64.b64encode(data).decode('utf-8')
                        await websocket.send(json.dumps({
                            "type": "data",
                            "payload": {"port": port, "data": encoded_data}
                        }))
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass
        
        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type")
                    payload = msg.get("payload", {})

                    if msg_type == "list_ports":
                        ports = self.serial_server.list_serial_ports()
                        await websocket.send(json.dumps({"type": "port_list", "payload": {"ports": ports}}))

                    elif msg_type == "subscribe_port":
                        port = payload.get("port")
                        baudrate = int(payload.get("baudrate", 115200))
                        if not port:
                            continue

                        if port not in self.serial_server.list_serial_ports():
                            # open_port will now trigger a notification, which is fine.
                            if not self.serial_server.open_port(port, baudrate=baudrate):
                                await websocket.send(json.dumps({"type": "error", "payload": {"message": f"Failed to open port {port}"}}))
                                continue
                        
                        if port not in subscriptions:
                            queue = self.serial_server.xterm_subscribe_read_bytes(port)
                            task = asyncio.create_task(forward_task(port, queue))
                            subscriptions[port] = {"queue": queue, "task": task}
                            
                            ports_info = self.serial_server.list_serial_ports()
                            port_info = ports_info.get(port, {})
                            await websocket.send(json.dumps({"type": "port_subscribed", "payload": {"port": port, "baudrate": port_info.get('baudrate', baudrate)}}))

                    elif msg_type == "unsubscribe_port":
                        port = payload.get("port")
                        if port and port in subscriptions:
                            sub = subscriptions.pop(port)
                            sub["task"].cancel()
                            self.serial_server.xterm_unsubscribe_read_bytes(sub["queue"], port)
                            await websocket.send(json.dumps({"type": "port_unsubscribed", "payload": {"port": port}}))

                    elif msg_type == "data":
                        port = payload.get("port")
                        data = payload.get("data")
                        if port and data:
                            self.serial_server.xterm_write_bytes(data.encode('utf-8'), port)

                except (json.JSONDecodeError, KeyError) as e:
                    await websocket.send(json.dumps({"type": "error", "payload": {"message": f"Invalid message format: {e}"}}))
        finally:
            self.clients.remove(websocket)
            for port, sub in subscriptions.items():
                sub["task"].cancel()
                self.serial_server.xterm_unsubscribe_read_bytes(sub["queue"], port)

    def start(self):
        async def main():
            self.loop = asyncio.get_running_loop()
            self.server = await websockets.serve(self._handler, self.host, self.port)
            await self.server.wait_closed()

        try:
            asyncio.run(main())
        except Exception as e:
            print(f"WebSocket server error: {e}")

    def stop(self):
        if self.server:
            self.server.close()


class Iperf3Server:
    def __init__(self, port=5201):
        """
        初始化iperf3服务器
        
        参数:
            port (int): 监听端口号，默认5201
        """
        self.port = port
        self.process = None

    def start(self):
        """
        启动 iperf3 服务器。
        """
        command = ["iperf3", "-s"]
        command.extend(["-p", str(self.port)])

        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
        except Exception as e:
            print(f"Failed to start iperf3 server: {e}")

    def stop(self):
        """
        停止 iperf3 服务器。
        """
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
                print("已停止iperf3服务")
            except subprocess.TimeoutExpired:
                self.process.kill()
                print("已强制停止iperf3服务")
            self.process = None
        else:
            print("iperf3 server is not running")

    def is_running(self):
        """
        检查 iperf3 服务器是否正在运行。
        """
        return self.process is not None and self.process.poll() is None


def run_server(http_host, http_port, ws_host, ws_port, rpc_host, rpc_port, iperf_port):
    """
    启动串口RPC服务、实时监控HTTP页面和其对应的WebSocket
    """
    server_instance = SerialServer()
    http_server = ThreadingHTTPServer((http_host, http_port), HttpServer)
    http_server.daemon_threads = True
    ws_server = WebsocketServer(ws_host, ws_port, server_instance)
    iperf_server = Iperf3Server(iperf_port)
    rpc_server = SimpleXMLRPCServer((rpc_host, rpc_port), requestHandler=RequestHandler, allow_none=True, logRequests=False)
    rpc_server.register_introspection_functions()
    rpc_server.register_instance(server_instance)

    print(f"AutoTest串口页面: http://{http_host}:{http_port}/")
    print(f"WebSocket服务监听: ws://{ws_host}:{ws_port}/")
    print(f"串口RPC服务监听: http://{rpc_host}:{rpc_port}/RPC2")
    print(f"IPERF3服务监听: port:{iperf_port}")

    rpc_thread = threading.Thread(target=rpc_server.serve_forever, name='SerialRPCServer', daemon=True)
    http_thread = threading.Thread(target=http_server.serve_forever, name='SerialHTTPServer', daemon=True)
    ws_thread = threading.Thread(target=ws_server.start, name='SerialWebSocketServer', daemon=True)
    iperf_thread = threading.Thread(target=iperf_server.start, name='Iperf3Server', daemon=True)

    rpc_thread.start()
    http_thread.start()
    ws_thread.start()
    iperf_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    finally:
        rpc_server.shutdown()
        http_server.shutdown()
        iperf_server.stop()
        ws_server.stop()
        rpc_server.server_close()
        http_server.server_close()
        server_instance.close_all()


def main():
    """脚本入口，解析命令行参数并启动服务。"""
    parser = argparse.ArgumentParser(description='Automa Serial RPC & Monitor Server')
    parser.add_argument('--http_host', type=str, default='0.0.0.0', help='HTTP 监控页面绑定的主机地址。')
    parser.add_argument('--http_port', type=int, default=80, help='HTTP 监控页面监听的端口。')
    parser.add_argument('--ws_host', type=str, default=None, help='WebSocket 监控页面绑定的主机地址。')
    parser.add_argument('--ws_port', type=int, default=11693, help='WebSocket 监控页面监听的端口。')
    parser.add_argument('--rpc_host', type=str, default=None, help='RPC 服务绑定的主机地址。')
    parser.add_argument('--rpc_port', type=int, default=11692, help='RPC 服务监听的端口。')
    parser.add_argument('--iperf_port', type=int, default=5201, help='Iperf3 服务监听的端口。')
    args = parser.parse_args()

    args.ws_host = args.ws_host or args.http_host
    args.rpc_host = args.rpc_host or args.http_host
    run_server(args.http_host, args.http_port, args.ws_host, args.ws_port, args.rpc_host, args.rpc_port,args.iperf_port)


if __name__ == '__main__':
    main()
