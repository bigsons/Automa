# -*- coding: utf-8 -*-
# tp_autotest/utils/serial_utils.py

import serial
import time
import re
import os
import threading
from collections import deque, defaultdict
from queue import Queue, Empty
from datetime import datetime, timedelta
from xmlrpc.client import ServerProxy
# =====================================================================================================================
#  内部使用的 SerialConnection (由 Server 进程建立和使用)
# =====================================================================================================================

class SerialConnection:
    """此类封装了对单个物理串口的所有操作。它在Server进程中被实例化。"""

    _SANITIZE_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')

    def __init__(self, ser_port, baudrate=115200, read_timeout=0, write_timeout=1, log_dir="./result", byte_broadcaster=None):
        """
        初始化SerialManager。

        Args:
            ser_port (str): 串口号 (例如: Windows上的 'COM3', Linux上的 '/dev/ttyUSB0').
            baudrate (int): 波特率.
            read_timeout (int): 读取超时时间 (秒).
            write_timeout (int): 写入超时时间 (秒).
            log_dir (str): 保存日志文件的目录路径.
        """
        self.ser = None
        self.port = ser_port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self.log_dir = log_dir
        self.byte_broadcaster = byte_broadcaster

        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        log_filename = f"serial_{ser_port.replace('/', '_').replace('.', '_')}.log"
        self.log_file = os.path.join(self.log_dir, log_filename)

        self.log_buffer = deque(maxlen=50000)
        self.read_queue = Queue()
        self.is_reading = False
        self.read_thread = None
        self.write_lock = threading.Lock()
        self.log_write_lock = threading.Lock()

        self._line_reconstruction_buffer = b''
        self._last_buffer_update_time = None
        self.read_buffer_size = 2048

    def _read_data_thread(self):
        """后台线程，持续读取串口数据，添加时间戳，并存入队列、缓冲区和文件。"""
        self._last_buffer_update_time = time.time()
        
        while self.is_reading and self.ser and self.ser.is_open:
            try:
                data = self.ser.read(self.read_buffer_size)
                if data:
                    self._last_buffer_update_time = time.time()
                    self.byte_broadcaster.publish(self.port, data)
                    self._line_reconstruction_buffer += data

                # 处理缓冲区中的数据
                while b'\n' in self._line_reconstruction_buffer:
                    line_bytes, self._line_reconstruction_buffer = self._line_reconstruction_buffer.split(b'\n', 1)
                    if self._line_reconstruction_buffer: # 如果分割后还有剩余，说明是个新的片段，更新时间
                        self._last_buffer_update_time = time.time()
                    
                    line_bytes = line_bytes.strip(b"\r")
                    timestamp = datetime.now()
                    try:
                        line = line_bytes.decode('utf-8', errors='ignore')
                    except UnicodeDecodeError:
                        line = f"[DECODE_ERROR] {line_bytes.hex()}"

                    if line:
                        line = self.clean_text(line)
                        if not line:
                            continue
                        log_entry = (timestamp, f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {line}")
                        self.log_buffer.append(log_entry)
                        self.read_queue.put(log_entry[1])
                        self._write_to_log_file(log_entry[1])

                # 处理超时逻辑：如果缓冲区有残留数据，并且在一段时间内没有更新，则强制刷出
                if self._line_reconstruction_buffer and (time.time() - self._last_buffer_update_time > 0.3):
                    line_bytes = self._line_reconstruction_buffer
                    self._line_reconstruction_buffer = b'' # 清空缓冲区

                    line_bytes = line_bytes.strip(b"\r")
                    timestamp = datetime.now()
                    try:
                        line = line_bytes.decode('utf-8', errors='ignore')
                    except UnicodeDecodeError:
                        line = f"[DECODE_ERROR] {line_bytes.hex()}"

                    if line:
                        line = self.clean_text(line)
                        if not line:
                            continue
                        log_entry = (timestamp, f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {line}")
                        self.log_buffer.append(log_entry)
                        self.read_queue.put(log_entry[1])
                        self._write_to_log_file(log_entry[1])

                time.sleep(0.01)

            except (serial.SerialException, OSError) as e:
                print(f"从串口 {self.port} 读取数据时出错: {e}. 停止线程。")
                self.is_reading = False
                break
            except Exception as e:
                print(f"_read_data_thread 发生未知错误: {e}")
                time.sleep(0.1) # Prevent busy-waiting on unknown errors

    def clean_text(self, text):
        if not text:
            return ""
        return self._SANITIZE_RE.sub('', text)

    def open(self):
        """打开串口，并启动后台日志记录线程。"""
        if self.ser and self.ser.is_open:
            print(f"串口 {self.port} 已经打开。")
            return True
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.read_timeout, write_timeout=self.write_timeout)
            print(f"串口 {self.port} 已成功打开。")

            self.is_reading = True
            self.read_thread = threading.Thread(target=self._read_data_thread, daemon=True)
            self.read_thread.start()
            return True
        except serial.SerialException as e:
            print(f"打开串口 {self.port} 失败: {e}")
            self.ser = None
            return False

    def close(self):
        """关闭串口并安全停止后台线程。"""
        if not self.is_reading and not (self.ser and self.ser.is_open):
            return

        self.is_reading = False
        if self.read_thread and self.read_thread.is_alive():
            try:
                self.ser.cancel_read()
            except AttributeError:
                pass

        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"串口 {self.port} 已关闭。")
        self.read_thread = None

    def write_bytes(self, data):
        """向串口发送原始字节数据。"""
        if not (self.ser and self.ser.is_open):
            return False
        with self.write_lock:
            self.ser.write(data)
        return True

    def login(self, username, password, timeout=10):
        if not (self.ser and self.ser.is_open):
            return False
        
        self._clear_read_queue()
        def wait_for_patterns(patterns, search_timeout):
            search_end_time = time.time() + search_timeout
            while time.time() < search_end_time:
                line = self._read_from_queue(timeout=1)
                if line and re.search(patterns, line, re.IGNORECASE):
                    return True
            return False
        self.send_cmd_quiet("") 
        if wait_for_patterns(r"(root@|#\s*$)", 2):
            return True
        self.send_cmd_quiet("")
        if not wait_for_patterns(r"login:|username:", 5):
            return False
        self.send_cmd_quiet(username)
        if not wait_for_patterns(r"password:", 5):
            return False
        self.send_cmd_quiet(password)
        return wait_for_patterns(r"busybox|root@|#\s*$", 5)

    def send_cmd(self, command, timeout=1):
        """
        向串口发送命令并立即返回。它不等待设备的回显。
        """
        if not (self.ser and self.ser.is_open):
            print(f"发送命令 '{command}' 失败: 串口未打开。")
            return False
        full_command_bytes = (command + '\n').encode('utf-8')
        try:
            self.write_bytes(full_command_bytes)
            timestamp = datetime.now()
            log_entry_str = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] ==== [{command}] ===="
            self._write_to_log_file(log_entry_str)
            return True
        except:
            return False

    def get_log(self, lines=None, duration=None):
        log_list = []
        buffer_copy = list(self.log_buffer)
        if duration is not None:
            time_threshold = datetime.now() - timedelta(seconds=duration)
            for timestamp, log_str in reversed(buffer_copy):
                if timestamp >= time_threshold:
                    log_list.append(log_str)
                else:
                    break
            return self.clean_text("\n".join(reversed(log_list)))
        elif lines is not None:
            return self.clean_text("\n".join([item[1] for item in buffer_copy[-lines:]]))

        return self.clean_text("\n".join([item[1] for item in buffer_copy]))

    def _extract_matches(self, line, regex, pattern):
        if regex:
            return [match.group(0) for match in regex.finditer(line)]
        if pattern in line:
            return [line]
        return []

    def search_log(self, pattern, lines=None, duration=None):
        """在日志中搜索模式，返回所有匹配结果及其上下文。"""
        log_to_search = self.get_log(lines=lines, duration=duration)
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = None

        results = []
        lines_to_scan = log_to_search.splitlines()
        for i, line in enumerate(lines_to_scan):
            matches_in_line = self._extract_matches(line, regex, pattern)
            if matches_in_line:
                context_start = max(0, i - 5)
                context_end = min(len(lines_to_scan), i + 6)
                context = "\n".join(lines_to_scan[context_start:context_end])
                for match in matches_in_line:
                    results.append({'match': match, 'line': line, 'context': context})
        return results

    def wait_for_log(self, pattern, timeout=10):
        """等待日志中出现特定模式，返回第一个匹配结果及其上文。"""
        end_time = time.time() + timeout
        try:
            regex = re.compile(pattern)
        except re.error:
            # Treat pattern as a literal string and escape it for regex
            regex = re.compile(re.escape(pattern))
        
        while time.time() < end_time:
            remaining = end_time - time.time()
            line = self._read_from_queue(timeout=min(0.1, remaining))
            if not line:
                continue

            match_obj = regex.search(line)
            if match_obj:
                match_str = match_obj.group(0)
                # Found a match, now get "before" context from the main buffer
                all_log_lines = [item[1] for item in self.log_buffer]
                try:
                    # Find the last occurrence of the line
                    line_index = len(all_log_lines) - 1 - all_log_lines[::-1].index(line)
                    context_start = max(0, line_index - 5)
                    context_end = line_index + 1  # Only include up to the matching line
                    context = "\n".join(all_log_lines[context_start:context_end])
                except ValueError:
                    context = line # Fallback
                
                # Return a single dictionary for the first match found
                return {'match': match_str, 'line': line, 'context': context}
        
        return None # Return None on timeout

    def _write_to_log_file(self, line):
        with self.log_write_lock:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except Exception as e:
                print(f"写入日志文件失败: {e}")

    def _read_from_queue(self, timeout=1):
        try:
            return self.read_queue.get(timeout=timeout)
        except Empty:
            return None
            
    def _clear_read_queue(self):
        while not self.read_queue.empty():
            try:
                self.read_queue.get_nowait()
            except Empty:
                break
                
    def send_cmd_quiet(self, command):
        if not (self.ser and self.ser.is_open):
            return
        self.write_bytes((command + '\n').encode('utf-8')) # Use new write_bytes method

# =====================================================================================================================
#  RPC服务进程上的SerialServer
# =====================================================================================================================
class SerialServer:
    """RPC服务器，使用物理端口号作为唯一标识符管理所有连接。"""

    def __init__(self):
        self.connections = {}
        self.lock = threading.Lock()
        self.byte_broadcaster = ByteBroadcaster()
        self.listeners = []

    def register_listener(self, listener):
        """注册一个监听器（回调函数），用于在事件发生时接收通知。"""
        if listener not in self.listeners:
            self.listeners.append(listener)

    def _notify_listeners(self, event, payload):
        """通知所有注册的监听器。"""
        for listener in self.listeners:
            try:
                listener(event, payload)
            except Exception as e:
                print(f"Error notifying listener {listener}: {e}")

    def xterm_subscribe_read_bytes(self, port=None):
        """订阅指定串口的原始字节数据。"""
        return self.byte_broadcaster.subscribe(port)

    def xterm_unsubscribe_read_bytes(self, queue, port=None):
        """取消订阅指定串口的原始字节数据。"""
        self.byte_broadcaster.unsubscribe(queue, port)

    def xterm_write_bytes(self, data, port):
        """向指定串口写入原始字节数据。"""
        conn = self._get_connection(port)
        return conn.write_bytes(data) if conn else False

    def _get_connection(self, port):
        """内部方法，安全地获取一个连接实例。"""
        with self.lock:
            return self.connections.get(port)

    def open_port(self, port, baudrate=115200, timeout=0, log_dir="./result"):
        """ 打开一个指定的串口。如果该串口已打开，则重用现有连接。"""
        with self.lock:
            if port in self.connections and self.connections[port].ser and self.connections[port].ser.is_open:
                print(f"串口 {port} 已经打开，复用现有连接。")
                return True
            connection = SerialConnection(port, baudrate, timeout, timeout, log_dir, byte_broadcaster=self.byte_broadcaster)
            if connection.open():
                self.connections[port] = connection
                print(f"串口 {port} 打开成功。")
                # Notify listeners
                self._notify_listeners('port_opened', {'port': port, 'baudrate': baudrate})
                return True
            else:
                print(f"错误：打开串口 {port} 失败。")
                return False

    def close_port(self, port):
        """关闭一个指定的串口连接。"""
        with self.lock:
            if port in self.connections:
                self.connections[port].close()
                del self.connections[port]
                print(f"移除串口 {port} 的连接")
                # Notify listeners
                self._notify_listeners('port_closed', {'port': port})
                return True
            print(f"警告：尝试关闭一个不存在的串口连接 {port}。")
            return False

    def close_all(self):
        """关闭所有已打开的串口连接。"""
        ports_to_close = []
        with self.lock:
            ports_to_close = list(self.connections.keys())
        for port in ports_to_close:
            self.close_port(port)
        print("所有已打开的串口均已关闭。")
        return True

    def list_serial_ports(self):
        """列出所有当前已连接的串口及其状态，供RPC调用。"""
        with self.lock:
            ports_info = {}
            for port, conn in self.connections.items():
                is_open = conn.ser and conn.ser.is_open if conn else False
                ports_info[port] = {
                    'port': conn.port,
                    'baudrate': conn.baudrate,
                    'is_open': is_open,
                }
            print(f"当前连接的串口: {list(ports_info.keys())}")
            return ports_info

    # 暴露给客户端的功能接口
    def send_cmd(self, command, port, timeout=1):
        conn = self._get_connection(port)
        return conn.send_cmd(command, timeout) if conn else False

    def login(self, username, password, port, timeout=10):
        conn = self._get_connection(port)
        return conn.login(username, password, timeout) if conn else False

    def get_log(self, lines, duration, port):
        conn = self._get_connection(port)
        return conn.get_log(lines=lines, duration=duration) if conn else ""

    def search_log(self, pattern, lines, duration, port):
        conn = self._get_connection(port)
        return conn.search_log(pattern, lines=lines, duration=duration) if conn else []

    def wait_for_log(self, pattern, port, timeout=10):
        conn = self._get_connection(port)
        return conn.wait_for_log(pattern, timeout=timeout) if conn else []

# =====================================================================================================================
#  串口日志广播器，供实时页面订阅使用
# =====================================================================================================================
class ByteBroadcaster:
    """广播原始字节数据给订阅者。"""
    def __init__(self):
        self._subscribers = defaultdict(set)
        self._lock = threading.Lock()

    def subscribe(self, port=None):
        key = port or "*"
        queue = Queue()
        with self._lock:
            self._subscribers[key].add(queue)
        return queue

    def unsubscribe(self, queue, port=None):
        key = port or "*"
        with self._lock:
            subscribers = self._subscribers.get(key)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(key, None)

    def publish(self, port, byte_data):
        if not byte_data:
            return
        keys = [port or "*", "*"]
        with self._lock:
            targets = []
            for key in keys:
                queues = self._subscribers.get(key)
                if queues:
                    targets.extend(list(queues))
        for queue in targets:
            try:
                queue.put_nowait(byte_data)
            except Exception:
                pass

# =====================================================================================================================
#  模块内部连接的 SerialServer 进程接口的实例
# =====================================================================================================================
class SerialClient:
    """
    串口功能的客户端，通过RPC与后台的SerialServer通信。
    这是一个单例，并使用 __getattr__ 魔法方法将所有未知调用转发到RPC服务器。
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SerialClient, cls).__new__(cls)
        return cls._instance

    def __init__(self, host='127.0.0.1', port=11692):
        if getattr(self, '_initialized', False):
            return
            
        # 在尝试连接前，先将 proxy 设置为 None
        self.proxy = None
        self.server_url = f"http://{host}:{port}"
        try:
            self.proxy = ServerProxy(self.server_url, allow_none=True)
            # 测试连接
            self.proxy.system.listMethods() 
            print(f"已成功连接到串口管理服务 at {self.server_url}")
        except Exception as e:
            print(f"错误: 无法连接到串口管理服务 at {self.server_url}。")
            # 确保连接失败时 proxy 仍然是 None
            self.proxy = None 
            raise ConnectionRefusedError(f"无法连接到串口服务: {e}") from e
        
        # 在成功初始化的最后设置标志位
        self._initialized = True

    def __getattr__(self, name):
        """
        魔法方法的核心。当尝试调用一个在SerialClient实例上不存在的方法时
        """
        # 增加对内部属性的保护，防止在初始化期间发生递归
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
            
        if self.proxy is None:
            # 如果未连接到服务器，则引发错误，清晰地告知用户问题所在
            raise ConnectionRefusedError("未连接到串口服务，无法执行任何操作。")

        # 返回一个可调用对象，该对象会调用远程服务器上同名的方法
        return getattr(self.proxy, name)

# 将 SerialManager 这个名字指向 SerialClient 类。
SerialManager = SerialClient
