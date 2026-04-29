import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import winreg
import zipfile

# 导入第三方库
import psutil
import serial
import serial.tools.list_ports
from jinja2 import Environment, FileSystemLoader
# 导入PySide6库
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal as pyqtSignal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QProgressBar,QSizePolicy,
                               QPushButton, QMessageBox, QRadioButton, QScrollArea,
                               QStackedWidget, QStyle, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

# =====================================================================================================================
# 全局变量
# =====================================================================================================================
MODULE_VERSION = "0.0.1"
SOURCE_DIR = os.path.abspath("./source")
TEST_SOURCE_ZIP = os.path.abspath("./source/automa.env")
PROGRAM_FILES_DIR = os.environ.get("ProgramFiles", "C:\\Program Files")
CHROME_TEST_DIR = os.path.join(PROGRAM_FILES_DIR, "Automa")
PORTABLE_PYTHON_DIR = os.path.join(CHROME_TEST_DIR, "Python39")
PORTABLE_PYTHON_EXE = os.path.join(PORTABLE_PYTHON_DIR, "python.exe")

# =====================================================================================================================
# 资源路径处理
# =====================================================================================================================
def resource_path(relative_path):
    """ 获取资源的绝对路径，以兼容开发环境和 PyInstaller 打包环境。 """
    try:
        # PyInstaller 创建的临时文件夹路径
        base_path = sys._MEIPASS
    except Exception:
        # 开发环境下的当前工作目录
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def find_python_executable(user_defined_path=None, allow_system_search=False, include_portable=True):
    """
    在系统中查找可用的 Python.exe。

    优先顺序：
    1. 用户指定的路径。
    2. Automa 下的便携式 Python 环境。
    3. 系统 PATH 中的其他 Python。
    """

    normalized = _normalize_python_path(user_defined_path)
    if normalized:
        return normalized

    if include_portable and os.path.isfile(PORTABLE_PYTHON_EXE):
        return PORTABLE_PYTHON_EXE

    if not allow_system_search:
        return None

    try:
        command = ['where', 'python']
        creation_flags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(command, capture_output=True, text=True, check=True, creationflags=creation_flags)

        for path in result.stdout.strip().split('\n'):
            path = path.strip()
            if not path or "WindowsApps" in path:
                continue

            candidate = _normalize_python_path(path)
            if not candidate:
                continue

            try:
                version_command = [candidate, "--version"]
                version_result = subprocess.run(
                    version_command,
                    capture_output=True,
                    text=True,
                    check=True,
                    creationflags=creation_flags
                )
                version_output = (version_result.stdout or "") + (version_result.stderr or "")
                match = re.search(r'Python (\d+)\.(\d+)', version_output)
                if match:
                    major, minor = int(match.group(1)), int(match.group(2))
                    if (3, 6) < (major, minor) <= (3, 12):
                        return candidate
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return None

def _normalize_python_path(path):
    """标准化用户传入的 Python 路径，确保最终指向 python.exe。"""
    if not path:
        return None

    candidate = os.path.expandvars(os.path.expanduser(path.strip().strip('"')))
    if os.path.isdir(candidate):
        candidate = os.path.join(candidate, "python.exe")

    if os.path.isfile(candidate) and os.path.basename(candidate).lower() == "python.exe":
        return os.path.normpath(candidate)

    return None

# =====================================================================================================================
# 自定义控件
# =====================================================================================================================
class NoFocusDelegate(QStyledItemDelegate):
    """表格委托，用于移除单元格被选中时的虚线框，优化视觉效果。 """

    def paint(self, painter, option, index):
        if option.state & QStyle.StateFlag.State_HasFocus:
            # 移除焦点状态
            option.state = option.state & ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class ClickableLineEdit(QLineEdit):
    """可以发出点击信号的 QLineEdit，用于实现点击选择文件的功能。 """
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()  # 发出点击信号
        super().mousePressEvent(event)


class DoubleClickLineEdit(QLineEdit):
    """需要双击才能进入编辑状态的 QLineEdit，用于修改参数名。 """

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setFrame(False)
        self.setStyleSheet("DoubleClickLineEdit { background-color: transparent; }")
        self.editingFinished.connect(self.on_editing_finished)

    def mouseDoubleClickEvent(self, event):
        """ 双击时，控件变为可编辑状态。 """
        self.setReadOnly(False)
        self.setFrame(True)
        self.setStyleSheet("")  # 恢复默认样式
        self.selectAll()
        self.setFocus()
        super().mouseDoubleClickEvent(event)

    def on_editing_finished(self):
        """ 编辑完成后，恢复为只读的标签样式。 """
        self.setReadOnly(True)
        self.setFrame(False)
        self.setStyleSheet("DoubleClickLineEdit { background-color: transparent; }")
        self.deselect()


# =====================================================================================================================
# 环境与依赖配置线程
# =====================================================================================================================
class EnvironmentAndDependenciesThread(QThread):
    """
    后台线程，用于处理整个环境的初始化过程，避免UI阻塞。
    执行流程：
    1. 检查并配置自动化环境。
    2. 检查是否存在有效的 Python 环境。
    3. 如果未找到，则从本地资源包静默安装 Python。
    4. 检查并安装所有必需的 pip 依赖库。
    """
    status_update = pyqtSignal(str)  # 状态文本更新信号
    log_update = pyqtSignal(str)  # 日志信息更新信号
    progress_update = pyqtSignal(int)  # 进度条更新信号
    finished = pyqtSignal(bool, str)  # 任务完成信号 (is_success, message)

    def __init__(self, required_packages, use_default_python=True, user_python_path=None, parent=None):
        super().__init__(parent)
        self.required_packages = required_packages
        self.python_exe = None
        self.user_python_path = user_python_path
        self.use_default_python = use_default_python
        self.runtime_python_exe = None

    def setup_chrome_test_environment(self):
        """
        检查并配置自动化环境。
        如果环境变量不存在，则解压相关文件并设置系统环境变量。
        """
        self.status_update.emit("正在检查自动化环境...")
        self.progress_update.emit(0)
        if os.path.isdir(CHROME_TEST_DIR) and "\\automa" in os.environ.get('PATH', '').lower():
            # 如果环境中已存在路径，则跳过配置
            return True
        self.log_update.emit("开始配置自动化环境...")

        try:
            source_zip = TEST_SOURCE_ZIP
            if not os.path.exists(source_zip):
                self.status_update.emit("错误: 未在source目录下找到依赖资源")
                return False
            self.log_update.emit(f"正在加载相关资源到 '{CHROME_TEST_DIR}'")
            with zipfile.ZipFile(source_zip, 'r') as zip_ref:
                zip_ref.extractall(PROGRAM_FILES_DIR)
            self.log_update.emit("资源加载完成")

            # 将资源目录添加到系统环境变量 PATH 中
            self.log_update.emit("正在更新系统环境变量 PATH...")
            key_path = r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
            access_flags = winreg.KEY_READ | winreg.KEY_WRITE
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access_flags)

            old_path, path_type = winreg.QueryValueEx(key, 'Path')
            if CHROME_TEST_DIR.lower() not in old_path.lower().split(';'):
                new_path = f"{CHROME_TEST_DIR};{old_path}"
                winreg.SetValueEx(key, 'Path', 0, path_type, new_path)
            else:
                new_path = old_path
            winreg.CloseKey(key)
            self.log_update.emit("系统环境变量更新成功。")

            # 需要广播消息以通知所有窗口环境变量已更改
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x1A
            SMTO_ABORTIFHUNG = 0x0002
            ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                                    SMTO_ABORTIFHUNG, 5000, None)
            # 更新当前进程的环境变量
            os.environ['PATH'] = new_path

            return True

        except PermissionError:
            self.status_update.emit("权限错误: 设置环境变量需要管理员权限。")
            self.log_update.emit("请使用管理员身份重启本程序。")
            return False
        except Exception as e:
            self.status_update.emit(f"配置自动化时发生未知错误。")
            self.log_update.emit(str(e))
            traceback.print_exc()
            return False

    def find_python_installer(self):
        """ 在 './source' 目录中查找 Python 安装程序。 """
        try:
            installer_pattern = re.compile(r"python-[\d\.]+(-amd64)?\.exe", re.IGNORECASE)
            for filename in os.listdir(SOURCE_DIR):
                if installer_pattern.match(filename):
                    return os.path.join(SOURCE_DIR, filename), None
            return None, "错误: 在 './source' 目录中未找到Python安装包。"
        except Exception as e:
            return None, f"查找Python安装包时出错: {e}"

    def install_python(self):
        """ 部署或安装 Python 环境，并返回是否成功。 """
        try:
            os.makedirs(PORTABLE_PYTHON_DIR, exist_ok=True)
        except PermissionError as e:
            self.status_update.emit("权限错误: 无法在 Program Files 下创建 Automa 目录。")
            self.log_update.emit(str(e))
            return False
        except Exception as e:
            self.status_update.emit(f"创建 Automa 目录失败: {e}")
            self.log_update.emit(str(e))
            return False

        installer_path, error_msg = self.find_python_installer()
        if error_msg:
            self.status_update.emit(error_msg)
            return False

        self.status_update.emit("未检测到便携式 Python，将尝试使用安装包部署...")
        self.log_update.emit("未找到便携式 Python 环境，正在使用安装包静默安装...")

        command = [
            installer_path,
            "/quiet",
            "InstallAllUsers=1",
            f"TargetDir={PORTABLE_PYTHON_DIR}",
            "PrependPath=0"
        ]
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            process = subprocess.Popen(command, startupinfo=startupinfo)
            for i in range(240):
                if process.poll() is not None:
                    break
                time.sleep(1)
            process.wait()

            if process.returncode != 0:
                self.status_update.emit(f"Python 安装失败，返回码: {process.returncode}")
                return False

            if os.path.isfile(PORTABLE_PYTHON_EXE):
                self.status_update.emit("Python 安装完成。")
                return True

            self.status_update.emit("Python 安装完成但未检测到 python.exe。")
            return False
        except Exception as e:
            self.status_update.emit(f"安装 Python 时出现错误: {e}")
            self.log_update.emit(str(e))
            return False

    def install_dependencies(self):
        """ 检查并安装所有缺失的 pip 依赖包，支持本地路径和网络路径。 """
        try:
            cmd = [self.python_exe, "-m", "pip", "list", "--format=json"]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo,
                                     encoding='utf-8')
            installed_list = json.loads(result.stdout)
            # 创建一个已安装包名字和版本的字典，{'pyserial': '3.5', ...}
            installed_packages = {pkg['name'].lower().replace('_', '-'): pkg['version'] for pkg in installed_list}
        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
            installed_packages = {}

        packages_to_install = []
        network_packages = []
        local_packages = []

        # 1. 将包分为本地包和网络包
        for pkg_spec in self.required_packages:
            if '/' in pkg_spec or '\\' in pkg_spec or os.path.sep in pkg_spec:
                local_packages.append(pkg_spec)
            else:
                network_packages.append(pkg_spec)
        
        # 2. 优先处理网络包
        for pkg_spec in network_packages:
            match = re.match(r'([a-zA-Z0-9_.-]+)', pkg_spec)
            if not match:
                self.log_update.emit(f"警告: 无法从 '{pkg_spec}' 解析包名，将直接尝试安装。")
                packages_to_install.append(pkg_spec)
                continue
            
            pkg_name = match.group(0).lower().replace('_', '-')
            if pkg_name not in installed_packages:
                packages_to_install.append(pkg_spec)

        # 3. 再处理本地包，检查版本
        for pkg_spec in local_packages:
            parts = pkg_spec.split('==')
            if len(parts) != 2:
                self.log_update.emit(f"警告: 本地包 '{pkg_spec}' 格式不正确，应为 '路径==版本'，已跳过。")
                continue
            
            path, required_version = parts
            
            # 从路径中提取包名
            basename = os.path.basename(path)
            pkg_name_match = re.match(r'([a-zA-Z0-9_.-]+)', basename)
            if not pkg_name_match:
                self.log_update.emit(f"警告: 无法从路径 '{path}' 中解析出包名，已跳过。")
                continue

            pkg_name = pkg_name_match.group(0).lower().replace('_', '-')
            
            installed_version = installed_packages.get(pkg_name)

            if installed_version != required_version:
                self.log_update.emit(f"检查到 '{pkg_name}' 版本不匹配或未安装。需要: {required_version}, 已安装: {installed_version or 'N/A'}")
                packages_to_install.append(path) # 安装时只需要路径
            
        if not packages_to_install:
            return True

        total_to_install = len(packages_to_install)
        self.status_update.emit("检查和配置依赖库...")

        # 4. 执行安装
        for i, package in enumerate(packages_to_install):
            self.log_update.emit(f"正在安装 {os.path.basename(package)} ({i + 1}/{total_to_install})...")
            
            is_local = os.path.exists(package)
            if is_local:
                command = [self.python_exe, "-m", "pip", "install", package]
            else:
                command = [
                    self.python_exe, "-m", "pip", "install", package,
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "--retries=3"
                ]

            result = subprocess.run(command, capture_output=True, text=True, startupinfo=startupinfo, encoding='utf-8')

            if result.returncode != 0:
                error_details = result.stderr[:200] if result.stderr else "未知错误"
                msg = f"安装 '{os.path.basename(package)}' 失败: {error_details}..."
                self.status_update.emit(msg)
                return False

        self.log_update.emit("所有依赖库安装完成。")
        return True

    def run(self):
        """ 线程的主执行函数。 """
        if not self.setup_chrome_test_environment():
            self.finished.emit(False, "配置自动化环境失败，请检查权限或文件。")
            return

        self.status_update.emit("正在检查Python环境...")
        normalized_user = _normalize_python_path(self.user_python_path)
        # if self.user_python_path and not normalized_user:
        #     self.log_update.emit(f"警告: 用户指定的 Python 路径无效，已忽略: {self.user_python_path}")

        selected_python = None
        if self.use_default_python:
            selected_python = find_python_executable(allow_system_search=False, include_portable=True)
            if not selected_python:
                if not self.install_python():
                    self.finished.emit(False, "自动安装Python失败，请手动安装后再试。")
                    return
                selected_python = find_python_executable(allow_system_search=False, include_portable=True)
        else:
            selected_python = normalized_user
            if not selected_python:
                selected_python = find_python_executable(None, allow_system_search=True, include_portable=False)

        if not selected_python:
            self.finished.emit(False, "未找到可用的 Python 解释器，请检查设置。")
            return

        self.python_exe = selected_python
        self.runtime_python_exe = self.python_exe

        if not self.install_dependencies():
            self.finished.emit(False, "依赖库自动安装失败，请检查网络或手动安装。")
            return

        self.status_update.emit("环境配置完成")
        self.finished.emit(True, "环境准备就绪")


# =====================================================================================================================
# 测试脚本执行逻辑
# =====================================================================================================================
def get_script_description(case_script):
    """ 从测试脚本文件中提取 __brief__ 字段作为描述。 """
    try:
        script_name = os.path.splitext(case_script)[0]
        script_path = os.path.join(os.getcwd(), "case", case_script, f"{script_name}.py")
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                content = f.read()
                # 使用正则表达式查找 __brief__
                match = re.search(r'\s*__brief__\s*=\s*["\'](.*?)["\']', content)
                if match:
                    return match.group(1).strip()
    except Exception as e:
        print(f"读取脚本 {case_script} 的描述信息时出错: {e}")
    return "暂无脚本描述"


def get_report_dir():
    """ 获取存放报告的根目录路径。 """
    return os.path.join(os.getcwd(), "result")


def get_log_dir(case, device, log_base_dir):
    """ 根据用例和设备名称生成一个安全的日志目录路径。 """
    # 替换掉设备名中可能导致路径问题的字符
    safe_device_name = device.replace(":", "_").replace(".", "_")
    log_dir = os.path.join(log_base_dir, case, safe_device_name)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_cases():
    """ 从 'case' 文件夹获取所有测试用例的名称列表。 """
    case_dir = os.path.join(os.getcwd(), "case")
    if not os.path.isdir(case_dir):
        os.makedirs(case_dir)
        return []

    # 返回所有子目录的名称，并排序
    return sorted([
        name for name in os.listdir(case_dir)
        if os.path.isdir(os.path.join(case_dir, name)) and name != 'utils' and name != 'common' and not name.startswith(('.', '_'))
    ])


class PortCheckThread(QThread):
    """在后台检查串口可用性的线程，避免因串口占用导致UI阻塞。 """
    finished = pyqtSignal(bool, str)  # (is_available, error_message)

    def __init__(self, port_name, parent=None):
        super().__init__(parent)
        self.port_name = port_name

    def run(self):
        """ 尝试打开和关闭指定串口，以检查其是否被占用。 """
        if not self.port_name or self.port_name == "不使用":
            self.finished.emit(True, "")
            return
        try:
            ser = serial.Serial(self.port_name)
            ser.close()
            self.finished.emit(True, "")
        except serial.SerialException:
            error_message = f"错误: 串口 '{self.port_name}' 已被占用或无法访问。"
            self.finished.emit(False, error_message)


class RunnerThread(QThread):
    """ 在一个独立的线程中运行 Airtest 测试脚本，以防UI阻塞。 """
    status_update = pyqtSignal(str)
    progress_update = pyqtSignal(int)
    finished = pyqtSignal(str)  # (report_path)
    log_update = pyqtSignal(str)

    def __init__(self, cases, settings, python_executable):
        super().__init__()
        self.cases = sorted(cases)
        self.settings = settings
        self.running = True
        self.process_list = []
        self.report_dir = get_report_dir()
        self.results_data = []
        self.python_executable = python_executable

    def _stream_reader(self, stream):
        """ 在一个专用线程中实时读取子进程的输出流。 """
        for line in iter(stream.readline, ''):
            if not self.running:
                break
            self.log_update.emit(line.strip())
        stream.close()

    def run(self):
        """ 线程的主执行函数，负责整个测试流程的调度。 """
        report_dir = self.report_dir
        log_base_dir = os.path.join(report_dir, 'log')

        if self.python_executable:
            self.log_update.emit(f"使用 Python 解释器: {self.python_executable}")

        # 清理上一次的报告目录
        if os.path.isdir(report_dir):
            try:
                shutil.rmtree(report_dir)
            except PermissionError as e:
                self.status_update.emit(f"清理报告目录失败: {e}")
                time.sleep(1)
                try:  # 失败后重试一次
                    shutil.rmtree(report_dir)
                except Exception as e_retry:
                    self.status_update.emit(f"重试清理失败: {e_retry}")
                    self.finished.emit("")
                    return
        os.makedirs(log_base_dir, exist_ok=True)

        try:
            total_cases = len(self.cases)
            for i, case in enumerate(self.cases):
                if not self.running:
                    break
                self.status_update.emit(f"正在运行: {case} ({i + 1}/{total_cases})")
                case_results = {'script': case, 'tests': {}}

                tasks = self.run_on_devices(case, ["default_device"], log_base_dir)

                for task in tasks:
                    if not self.running:
                        break
                    # 等待子进程执行完毕
                    while task['process'].poll() is None:
                        if not self.running:
                            task['process'].terminate()
                            break
                        time.sleep(0.1)
                    if not self.running:
                        break

                    status = task['process'].returncode
                    # 生成单个用例的报告
                    report_info = self.run_one_report(task['case'], task['dev'], log_base_dir)
                    report_info['status'] = status if status is not None else -1
                    case_results['tests'][task['dev']] = report_info
                if self.running:
                    self.results_data.append(case_results)
                self.progress_update.emit(int(((i + 1) / total_cases) * 100))

            if self.results_data and self.results_data != []:
                self.progress_update.emit(100)
                report_path = ""
                report_path = self.run_summary(self.results_data, self.settings['start_time'])

                if self.running:
                    self.status_update.emit("所有脚本运行完毕。")
                else:
                    self.status_update.emit("用例已手动停止，已生成部分用例报告。")
                self.finished.emit(report_path)
            else:
                self.status_update.emit("运行已停止。")
                self.finished.emit("")
        except Exception as e:
            self.status_update.emit(f"发生错误: {e}")
            traceback.print_exc()
            self.finished.emit("")

    def run_on_devices(self, case, devices, log_base_dir):
        """ 为单个用例启动一个或多个 Airtest 子进程。 """
        tasks = []
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.join(os.getcwd(), "case")
        env['PROJECT_ROOT'] = os.getcwd()
        env['PYTHONUNBUFFERED'] = "1"  # 强制不缓存输出，以便实时读取日志

        case_name = os.path.splitext(case)[0]
        case_path = os.path.join(os.getcwd(), "case", case, f"{case_name}.py")
        if not self.python_executable:
            self.status_update.emit("错误: 未找到 Python 环境，无法执行 Airtest 用例。")
            return tasks

        for dev in devices:
            log_dir = get_log_dir(case, dev, log_base_dir)
            cmd = [
                self.python_executable,
                "-m", "airtest",
                "run", case_path,
                "--log", log_dir,
                "--recording"
            ]

            try:
                is_windows = (os.name == 'nt')
                creation_flags = subprocess.CREATE_NO_WINDOW if is_windows else 0

                self.log_update.emit(f"运行脚本: {case_path}")
                process = subprocess.Popen(
                    cmd,
                    env=env,
                    cwd=os.getcwd(),
                    shell=False,
                    creationflags=creation_flags,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # 合并标准输出和错误
                    text=True,
                    encoding='gbk',  # Airtest 在 Windows 上的默认编码
                    errors='replace',
                    bufsize=1  # 行缓冲
                )

                # 启动一个守护线程来读取子进程的输出
                output_thread = threading.Thread(
                    target=self._stream_reader,
                    args=(process.stdout,),
                    daemon=True
                )
                output_thread.start()

                self.process_list.append(process)
                tasks.append({'process': process, 'dev': dev, 'case': case})
            except Exception:
                traceback.print_exc()
        return tasks

    def run_one_report(self, case, dev, log_base_dir):
        """ 为单次用例运行生成 HTML 报告。 """
        log_dir = get_log_dir(case, dev, log_base_dir)
        log_txt = os.path.join(log_dir, 'log.txt')
        case_name = os.path.splitext(case)[0]
        case_path = os.path.join(os.getcwd(), "case", case, f"{case_name}.py")

        if not self.python_executable:
            return {'status': -1, 'path': ''}

        # 脚本执行后，日志文件可能不会立即释放，尝试多次读取
        for attempt in range(5):
            if os.path.isfile(log_txt):
                try:
                    with open(log_txt, 'r', encoding='utf-8') as f:
                        f.read(1)  # 尝试读取一个字符
                    break  # 读取成功则跳出循环
                except (PermissionError, IOError):
                    if attempt < 4:
                        time.sleep(0.5)
                else:
                    return {'status': -1, 'path': ''}
            else:
                time.sleep(0.5)

        if not os.path.isfile(log_txt):
            return {'status': -1, 'path': ''}

        try:
            report_path = os.path.join(log_dir, 'log.html')
            cmd = [
                self.python_executable,
                "-m", "airtest",
                "report", case_path,
                "--log_root", log_dir,
                "--outfile", report_path,
                "--lang", "zh",
                "--plugin", "tp_autotest.report"
            ]
            is_windows = (os.name == 'nt')
            creation_flags = subprocess.CREATE_NO_WINDOW if is_windows else 0
            self.log_update.emit(f"生成报告: {case_path}")
            report_process = subprocess.Popen(
                cmd,
                shell=False,
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation_flags
            )
            report_process.communicate(timeout=60)

            relative_path = os.path.relpath(report_path, self.report_dir).replace('\\', '/')
            return {'status': 0, 'path': relative_path}
        except Exception:
            traceback.print_exc()
            return {'status': -1, 'path': ''}

    def run_summary(self, data, start_time):
        """ 使用 Jinja2 模板生成最终的汇总报告。 """
        try:
            summary = {
                'time': f"{(time.time() - start_time):.3f}",
                'success': sum(1 for dt in data for test in dt['tests'].values() if test.get('status') == 0),
                'count': sum(len(dt['tests']) for dt in data),
                'start_all': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time)),
                "result": data,
                "model_name": self.settings.get("model_name", "N/A"),
                "model_version": self.settings.get("model_version", "N/A"),
            }
            for dt in data:
                dt['description'] = get_script_description(dt['script'])

            env = Environment(loader=FileSystemLoader(SOURCE_DIR), trim_blocks=True)
            template = env.get_template('template.html')
            html = template.render(data=summary)

            report_path = os.path.join(self.report_dir, "result.html")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(html)

            # 返回可直接在浏览器中打开的本地文件URL
            return 'file:///' + os.path.realpath(report_path).replace('\\', '/')
        except Exception:
            traceback.print_exc()
            return ""

    def stop(self):
        """ 停止测试线程和所有由它创建的子进程。 """
        self.running = False

        # 停止所有airtest子进程
        for p in self.process_list:
            if p.poll() is None:
                try:
                    parent = psutil.Process(p.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    parent.kill()
                except Exception as e:
                    self.log_update.emit(f"停止进程 (PID: {p.pid}) 时出错: {e}")

        self.process_list.clear()


# =====================================================================================================================
# 其他参数设置页面
# =====================================================================================================================
class OtherSettingsPage(QWidget):
    """ 用于显示和编辑主界面之外的其他参数。 """
    MAIN_UI_KEYS = {
        "model_name", "model_version", "model_path", "default_serial",
        "wired_adapter", "wireless_adapter", "adapter_support_6g", "selected_scripts",
        "python_path", "use_default_python"
    }

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._setup_ui()

    def _setup_ui(self):
        """ 初始化UI组件。 """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        top_header_layout = QHBoxLayout()
        title_label = QLabel("其他参数设置", objectName="titleLabel")
        top_header_layout.addWidget(title_label)
        top_header_layout.addStretch()
        back_button = QPushButton(" 返回主页")
        back_button.setIcon(QIcon(resource_path("static/back.png")))
        back_button.setObjectName("subtleTextButton")
        back_button.setToolTip("返回主页")
        back_button.setIconSize(QSize(12, 12))
        back_button.clicked.connect(lambda: self.main_window.stacked_widget.setCurrentIndex(0))
        top_header_layout.addWidget(back_button)
        layout.addLayout(top_header_layout)

        second_header_layout = QHBoxLayout()
        self.card_title = QLabel("自定义参数列表", objectName="cardTitle")
        self.card_title.setStyleSheet("padding-left: 5px;")
        second_header_layout.addWidget(self.card_title)
        second_header_layout.addStretch()
        add_button = QPushButton()
        add_button.setIcon(QIcon(resource_path("static/add.png")))
        add_button.setObjectName("iconButton")
        add_button.setToolTip("添加参数条目")
        add_button.setFixedSize(24, 24)
        add_button.setIconSize(QSize(14, 14))
        add_button.clicked.connect(self.add_parameter)
        second_header_layout.addWidget(add_button)
        layout.addLayout(second_header_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("card")
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.params_container = QWidget()
        self.params_container.setStyleSheet("background-color: transparent;")

        self.params_grid = QGridLayout(self.params_container)
        self.params_grid.setContentsMargins(15, 15, 15, 15)
        self.params_grid.setHorizontalSpacing(10)
        self.params_grid.setVerticalSpacing(8)
        self.params_grid.setColumnStretch(0, 1)
        self.params_grid.setColumnStretch(2, 4)

        self.scroll_area.setWidget(self.params_container)
        layout.addWidget(self.scroll_area)
        layout.addStretch(1)

    @staticmethod
    def _value_to_string(value):
        if value is None:
            return "null"
        try:
            return json.dumps(value)
        except TypeError:
            return str(value)

    def _clear_grid_layout(self):
        while self.params_grid.count():
            item = self.params_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def update_dynamic_height(self, num_rows):
        """ 根据参数条目的数量，动态计算并设置滚动区域的高度。 """
        if num_rows == 0:
            self.scroll_area.setMinimumHeight(60)
            self.scroll_area.setMaximumHeight(60)
        else:
            base_padding = 30
            row_height = 38
            extra_height = 8
            max_visible_rows = 15
            target_height = base_padding + (num_rows * row_height)
            max_height = base_padding + (max_visible_rows * row_height) + extra_height
            final_height = min(target_height, max_height)
            self.scroll_area.setMinimumHeight(final_height)
            self.scroll_area.setMaximumHeight(final_height)

    def load_other_settings(self):
        """ 从主窗口的配置中加载所有“其他”参数并显示在界面上。 """
        self._clear_grid_layout()
        settings = self.main_window.settings
        other_params = {k: v for k, v in settings.items() if k not in self.MAIN_UI_KEYS}
        param_keys = list(other_params.keys())

        last_row_index = 0
        for i, key in enumerate(param_keys):
            value = other_params[key]
            last_row_index = i

            key_editor = DoubleClickLineEdit(key)
            colon_label = QLabel(":")
            colon_label.setFixedWidth(10)
            colon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_editor = QLineEdit(self._value_to_string(value))
            delete_button = QPushButton()
            delete_button.setIcon(QIcon(resource_path("static/delete.png")))
            delete_button.setObjectName("iconButton")
            delete_button.setToolTip(f"删除参数 '{key}'")
            delete_button.setFixedSize(24, 24)
            delete_button.setIconSize(QSize(12, 12))

            value_container = QWidget()
            value_container.setStyleSheet(f"""
                QToolTip {{background-color: white; color:black; }}
            """)
            value_hbox = QHBoxLayout(value_container)
            value_hbox.setContentsMargins(0, 0, 0, 0)
            value_hbox.setSpacing(5)
            value_hbox.addWidget(value_editor, 1)
            value_hbox.addWidget(delete_button)

            # 连接信号与槽
            key_editor.editingFinished.connect(
                lambda old_key=key, editor=key_editor: self.update_parameter_key(old_key, editor)
            )
            value_editor.editingFinished.connect(
                lambda k_editor=key_editor, v_editor=value_editor: self.update_setting(k_editor, v_editor)
            )
            delete_button.clicked.connect(
                lambda checked=False, key_to_delete=key: self.delete_parameter(key_to_delete)
            )

            self.params_grid.addWidget(key_editor, i, 0)
            self.params_grid.addWidget(colon_label, i, 1)
            self.params_grid.addWidget(value_container, i, 2)

        # 添加一个弹簧，使条目向上对齐
        self.params_grid.setRowStretch(last_row_index + 1, 1)
        self.update_dynamic_height(num_rows=len(param_keys))

    def add_parameter(self):
        """ 在参数列表中添加一个新的、唯一的参数条目。 """
        i = 1
        while True:
            new_key = f"new_param_{i}"
            if new_key not in self.main_window.settings:
                break
            i += 1

        self.main_window.settings[new_key] = None
        self.main_window.save_settings_silently()
        self.load_other_settings()
        self.main_window.status_label.setText(f"已添加新条目: '{new_key}', 请修改。")

    def delete_parameter(self, key_to_delete):
        """ 从配置中删除指定的参数条目。 """
        if key_to_delete in self.main_window.settings:
            del self.main_window.settings[key_to_delete]
            self.main_window.save_settings_silently()
            self.load_other_settings()

    def update_parameter_key(self, old_key, key_editor):
        """ 当参数的键（Key）被修改时调用，处理重命名逻辑。 """
        new_key = key_editor.text().strip()

        if not new_key or new_key == old_key:
            key_editor.setText(old_key)
            return

        if new_key in self.main_window.settings or new_key in self.MAIN_UI_KEYS:
            self.main_window.status_label.setText(f"错误: 参数名 '{new_key}' 已存在或为保留字!")
            key_editor.setText(old_key)
            return

        new_settings = {}
        for k, v in self.main_window.settings.items():
            if k == old_key:
                new_settings[new_key] = v
            else:
                new_settings[k] = v

        self.main_window.settings = new_settings
        self.main_window.save_settings_silently()
        self.load_other_settings()
        self.main_window.status_label.setText(f"参数 '{old_key}' 已重命名为 '{new_key}'")

    def update_setting(self, key_editor, value_editor):
        key = key_editor.text()
        if key not in self.main_window.settings:
            return

        new_text_value = value_editor.text()
        try:
            # 尝试将输入的值解析为 JSON，以支持 boolean, number 等类型
            new_typed_value = json.loads(new_text_value)
        except json.JSONDecodeError:
            # 如果解析失败，则将其视为普通字符串
            new_typed_value = new_text_value

        self.main_window.settings[key] = new_typed_value
        self.main_window.save_settings_silently()
        self.main_window.status_label.setText(f"参数 '{key}' 的值已更新。")


# =====================================================================================================================
# 设置对话框
# =====================================================================================================================
class SettingsDialog(QDialog):
    """ 设置对话框，提供导入和导出配置文件的功能。 """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("设置")
        self.setFixedWidth(540)
        self.setMinimumHeight(530)
        self._setup_ui()
        self._load_initial_state()

    def _setup_ui(self):
        """ 初始化对话框UI。 """
        primary_color = "#4F46E5"
        primary_hover_color = "#4338CA"
        card_bg_color = "#FFFFFF"
        border_color = "#E5E7EB"
        secondary_text_color = "#6B6480"

        self.setStyleSheet(f"""
            QDialog {{ background-color: #F8F9FA; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; }}
            QFrame#card {{ background-color: {card_bg_color}; border: 1px solid {border_color}; border-radius: 8px; }}
            QFrame#card QRadioButton {{ background-color: transparent; }}
            QLabel#headerLabel {{ font-size: 14px; font-weight: 600; padding-bottom: 4px; }}
            QLabel#aboutValueLabel {{ font-size: 12px; font-weight: 500; }}
            QFrame#separator {{ border-top: 1px solid {border_color}; }}
            QPushButton#linkButton {{ background-color: transparent; color: {primary_color}; border: none; padding: 0; margin: 0; text-align: left; font-size: 12px; }}
            QPushButton#linkButton:hover {{ text-decoration: underline; }}
            QRadioButton {{ font-size: 12px; padding: 4px 0; }}
            QLineEdit {{ padding: 6px; border: 1px solid {border_color}; border-radius: 5px; font-size: 12px; }}
            QLineEdit:focus {{ border: 1px solid {primary_color}; }}
            QPushButton#purpleButton {{ background-color: {primary_color}; color: #FFFFFF; border: none; padding: 6px 12px; border-radius: 5px; font-size: 12px; font-weight: 500; }}
            QPushButton#purpleButton:hover {{ background-color: {primary_hover_color}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(15)

        # --- Python 环境卡片 ---
        python_card = QFrame(objectName="card")
        python_layout = QVBoxLayout(python_card)
        python_layout.setContentsMargins(15, 10, 15, 15)
        python_layout.setSpacing(8)

        python_header = QLabel("Python 环境", objectName="headerLabel")
        python_layout.addWidget(python_header)
        
        python_intro = QLabel("选择用于运行测试用例的 Python 解释器")
        python_intro.setStyleSheet(f"color: {secondary_text_color}; font-size: 12px; padding-bottom: 8px;")
        python_layout.addWidget(python_intro)

        self.portable_radio = QRadioButton("使用内置环境 (推荐)")
        python_layout.addWidget(self.portable_radio)
        self.custom_radio = QRadioButton("使用自定义解释器")
        python_layout.addWidget(self.custom_radio)

        self.custom_python_container = QWidget()
        self.custom_python_container.setStyleSheet("background-color: transparent;")
        custom_container_layout = QVBoxLayout(self.custom_python_container)
        custom_container_layout.setContentsMargins(0, 8, 0, 0)
        custom_container_layout.setSpacing(6)

        self.python_path_entry = ClickableLineEdit()
        self.python_path_entry.setReadOnly(True)
        self.python_path_entry.setPlaceholderText("点击选择Python环境，留空则运行时自动查找")
        path_entry_layout = QHBoxLayout(self.python_path_entry)
        path_entry_layout.setContentsMargins(0, 0, 4, 0)
        self.clear_button = QPushButton(QIcon(resource_path("static/clear.png")), "")
        self.clear_button.setFixedSize(22, 22)
        self.clear_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.clear_button.setStyleSheet("QPushButton { border: none; border-radius: 11px; padding: 0; background-color: transparent; } QPushButton:hover { background-color: #E5E7EB; }")
        self.clear_button.clicked.connect(self.python_path_entry.clear)
        path_entry_layout.addStretch()
        path_entry_layout.addWidget(self.clear_button)
        custom_container_layout.addWidget(self.python_path_entry)

        self.path_error_label = QLabel("")
        self.path_error_label.setStyleSheet("color: #EF4444; font-size: 12px;")
        self.path_error_label.setWordWrap(True)
        self.path_error_label.setVisible(False)
        custom_container_layout.addWidget(self.path_error_label)
        python_layout.addWidget(self.custom_python_container)
        layout.addWidget(python_card)

        # --- 配置文件卡片 ---
        config_card = QFrame(objectName="card")
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(15, 10, 15, 15)
        config_layout.setSpacing(10)
        config_header = QLabel("配置文件", objectName="headerLabel")
        config_layout.addWidget(config_header)
        config_hint = QLabel("导入或导出配置，方便切换机型测试与备份共享")
        config_hint.setStyleSheet(f"color: {secondary_text_color}; font-size: 12px; padding-bottom: 5px;")
        config_layout.addWidget(config_hint)

        bottom_container = QHBoxLayout()
        # bottom_container.setContentsMargins(2, 0, 0, 0) # 确保没有多余的边距
        self.config_error_label = QLabel("")
        self.config_error_label.setStyleSheet("color: #EF4444; font-size: 12px;")
        self.config_error_label.setWordWrap(True)
        self.config_error_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bottom_container.addWidget(self.config_error_label, 3) # 第2个参数为拉伸因子
        bottom_container.addStretch(1)
        import_button = QPushButton("导入配置...", objectName="purpleButton")
        import_button.clicked.connect(self.import_config_file)
        bottom_container.addWidget(import_button)
        export_button = QPushButton("导出配置...", objectName="purpleButton")
        export_button.clicked.connect(self.export_config_file)
        bottom_container.addWidget(export_button)
        config_layout.addLayout(bottom_container)
        layout.addWidget(config_card)
        
        # --- 软件信息卡片 ---
        about_card = QFrame(objectName="card")
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(15, 10, 15, 20)
        about_layout.setSpacing(12)
        about_header = QLabel("关于软件", objectName="headerLabel")
        about_layout.addWidget(about_header)
        
        info_body_layout = QHBoxLayout()
        info_body_layout.setSpacing(20)
        
        logo_label = QLabel()
        logo_label.setPixmap(QIcon(resource_path("static/logo.png")).pixmap(QSize(65, 65)))
        info_body_layout.addWidget(logo_label)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        app_name_label = QLabel("Automa Autotest")
        app_name_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        text_layout.addWidget(app_name_label)
        
        version_label = QLabel(f"版本号: {MODULE_VERSION}")
        version_label.setStyleSheet("color: #6B6480; font-size: 11px;")
        text_layout.addWidget(version_label)
        text_layout.addSpacing(3)
        
        description_layout = QHBoxLayout()
        description_layout.setContentsMargins(0,0,0,0)
        description_label = QLabel("辅助自测流程的自动化工具，不可完全代替手测")
        description_label.setStyleSheet(f"color: {secondary_text_color}; font-size: 12px;")
        # 设置水平策略为Expanding，让它优先占据空间
        description_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        description_label.setWordWrap(True)

        update_button = QPushButton("查看文档", objectName="linkButton")
        update_button.clicked.connect(lambda: webbrowser.open("https://rdconfluence.tp-link.com/pages/viewpage.action?pageId=491659783"))
        
        description_layout.addWidget(description_label)
        description_layout.addWidget(update_button)
        text_layout.addLayout(description_layout)

        text_layout.addStretch(1)
        info_body_layout.addLayout(text_layout, 1)
        about_layout.addLayout(info_body_layout)
        
        layout.addWidget(about_card)

        layout.addStretch(1)

        # --- 连接信号 ---
        self.portable_radio.toggled.connect(self._on_mode_changed)
        self.python_path_entry.clicked.connect(self.select_python_path)
        self.python_path_entry.textChanged.connect(self._on_path_changed)

    def _open_root_directory(self):
        """打开应用程序的根目录。"""
        try:
            path = os.path.realpath(os.getcwd())
            webbrowser.open(f"file:///{path}")
        except Exception as e:
            self.path_error_label.setText(f"无法打开目录: {e}")
            self.path_error_label.setVisible(True)

    def _load_initial_state(self):
        """ 根据保存的设置初始化UI状态 """
        use_portable = self.main_window.settings.get("use_default_python", True)
        self.portable_radio.blockSignals(True)
        self.custom_radio.blockSignals(True)
        self.portable_radio.setChecked(use_portable)
        self.custom_radio.setChecked(not use_portable)
        self.portable_radio.blockSignals(False)
        self.custom_radio.blockSignals(False)
        saved_path = self.main_window.settings.get("python_path", "")
        self.python_path_entry.setText(saved_path)
        self._update_ui_for_mode(use_portable)
        self._update_clear_button_visibility(saved_path)
        if not use_portable:
            self._validate_path(saved_path)

    def _on_mode_changed(self):
        """ 当单选按钮状态改变时调用 """
        use_portable = self.portable_radio.isChecked()
        self._update_ui_for_mode(use_portable)
        self.main_window.settings["use_default_python"] = use_portable
        self.main_window.is_using_portable_python = use_portable
        if use_portable:
            self.main_window.status_label.setText("已切换为内置 Python 环境。")
        else:
            if not self.python_path_entry.text():
                candidate = find_python_executable(allow_system_search=True, include_portable=False)
                if candidate:
                    self.python_path_entry.setText(candidate)
                    self.main_window.status_label.setText("已自动识别系统中的 Python 解释器。")
                else:
                    self.main_window.status_label.setText("未找到可用Python，请手动指定。")
            else:
                self.main_window.status_label.setText("已切换为自定义 Python 环境。")
            self._validate_path(self.python_path_entry.text())
        self.main_window.save_settings_silently()

    def _update_ui_for_mode(self, use_portable):
        """ 根据选择的模式显示/隐藏相关UI控件 """
        self.custom_python_container.setVisible(not use_portable)

    def select_python_path(self):
        """ 弹出文件对话框选择python.exe """
        current_path = self.python_path_entry.text().strip()
        initial_dir = os.path.dirname(current_path) if current_path else os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 Python 可执行文件", initial_dir, "Python Executable (python.exe)"
        )
        if file_path:
            self.python_path_entry.setText(os.path.normpath(file_path))

    def _on_path_changed(self, path_text):
        """ 当路径文本改变时，验证、保存并更新UI """
        self._update_clear_button_visibility(path_text)
        if not self.custom_radio.isChecked():
            return
        self._validate_path(path_text)
        self.main_window.settings["python_path"] = self.python_path_entry.text()
        self.main_window.save_settings_silently()

    def _update_clear_button_visibility(self, text):
        """ 根据输入框内容显示或隐藏手动创建的清除按钮 """
        self.clear_button.setVisible(bool(text))
        if bool(text):
            self.python_path_entry.setTextMargins(0, 0, 28, 0)
        else:
            self.python_path_entry.setTextMargins(0, 0, 0, 0)

    def _validate_path(self, path_text):
        """ 仅验证路径，不保存。返回布尔值。"""
        path_text = path_text.strip()
        if not path_text:
            self.path_error_label.setVisible(False)
            return True
        normalized_path = _normalize_python_path(path_text)
        if normalized_path:
            self.path_error_label.setVisible(False)
            if self.python_path_entry.text() != normalized_path:
                self.python_path_entry.blockSignals(True)
                self.python_path_entry.setText(normalized_path)
                self.python_path_entry.blockSignals(False)
            return True
        else:
            self.path_error_label.setText(" 路径无效，请确保它指向一个有效的 python.exe 文件。")
            self.path_error_label.setVisible(True)
            return False
            
    def import_config_file(self):
        """ 导入 JSON 配置文件，并正确处理旧参数。 """
        self.config_error_label.setVisible(False)
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要导入的配置文件", "", "JSON Files (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                imported_settings = json.load(f)

            current_settings = self.main_window.settings
            other_params_keys = [k for k in current_settings if k not in self.main_window.MAIN_UI_KEYS]
            for k in other_params_keys:
                del current_settings[k]
            current_settings.update(imported_settings)

            # 验证导入的 Python 路径，如果无效则清空
            imported_python_path = current_settings.get("python_path", "")
            if imported_python_path and not _normalize_python_path(imported_python_path):
                current_settings["python_path"] = ""
                self.main_window.status_label.setText("提示: 导入的Python路径无效，已自动清除。")
            
            self.main_window.populate_ui_from_settings()
            self._load_initial_state()
            self.main_window.select_all_checkbox.setChecked(False)
            self.main_window.save_settings_silently()
            self.main_window.status_label.setText(f"已成功导入配置: {os.path.basename(file_path)}")
            self.close()
        except (json.JSONDecodeError, IOError) as e:
            self.config_error_label.setText(f"导入失败，请选择有效的JSON文件")
            self.config_error_label.setVisible(True)

    def export_config_file(self):
        """ 导出当前的用户参数到 JSON 文件。 """
        self.config_error_label.setVisible(False)
        self.main_window.save_settings_silently()
        model_name = self.main_window.settings.get("model_name", "model")
        version = self.main_window.settings.get("model_version", "version")
        default_filename = f"{model_name}_{version}_setting.json"
        file_path, _ = QFileDialog.getSaveFileName(self, "导出配置文件", default_filename, "JSON Files (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.main_window.settings, f, indent=2, ensure_ascii=False)
            self.main_window.status_label.setText(f"配置已导出至: {os.path.basename(file_path)}")
            self.close()
        except IOError as e:
            self.config_error_label.setText(f"导出失败: {e}")
            self.config_error_label.setVisible(True)


# =====================================================================================================================
# 主应用程序界面
# =====================================================================================================================
class App(QWidget):
    """ 应用程序的主窗口类。 """

    def __init__(self):
        super().__init__()
        self.settings = {}
        self.settings_path = "setting.json"
        self.runner_thread = None
        self.port_check_thread = None
        self.setup_thread = None
        self.server_process = None
        self.server_started_by_user = False
        self.server_button = None
        self.start_time = 0
        self.dont_confirm = False  # "不再提示"删除确认
        self.MAIN_UI_KEYS = OtherSettingsPage.MAIN_UI_KEYS
        self.resolved_python_executable = None
        self.runtime_python_executable = None
        self.is_using_portable_python = True
        self._scripts_table_signal_connected = False

        self.execution_timer = QTimer(self)
        self.execution_timer.timeout.connect(self.update_execution_time)
        # 用于标记程序是否因提权或安装依赖后自动重启
        self.is_restarting_after_install = "--post-install" in sys.argv

        self.setup_ui()
        self.load_settings()

        self.is_using_portable_python = self.settings.get("use_default_python", True)

        # 如果程序以自动启动参数运行，则延时启动测试
        if "--autostart" in sys.argv or self.is_restarting_after_install:
            QTimer.singleShot(100, self.start_runner)

    def closeEvent(self, event):
        """
        重写窗口关闭事件，以确保在退出前能安全地停止所有后台线程和子进程。
        """
        self.status_label.setText("正在关闭，请稍候...")
        # 禁用主窗口，防止用户在关闭过程中进行其他操作
        self.setEnabled(False)

        # 检查测试线程是否存在并且正在运行
        if self.runner_thread and self.runner_thread.isRunning():
            print("检测到测试线程仍在运行，正在停止...")
            self.runner_thread.stop()
            # 等待线程结束，给它一点时间来终止子进程
            if not self.runner_thread.wait(5000):
                print("警告: 停止测试线程超时。")

        # 检查并关闭手动或自动启动的服务
        if self.server_process and self.server_process.poll() is None:
            self._stop_server()

        # 接受关闭事件，允许窗口关闭
        event.accept()
        super().closeEvent(event)

    def setup_ui(self):
        """ 初始化主窗口UI。 """
        self.setWindowTitle("Automa")
        self.setWindowIcon(QIcon(resource_path("static/logo.png")))
        self.setGeometry(100, 100, 880, 640)

        self._set_stylesheet()

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧侧边栏
        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel)

        # 右侧主内容区 (使用 QStackedWidget 实现页面切换)
        main_page = self._create_main_page()
        self.other_settings_page = OtherSettingsPage(self)

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(main_page)
        self.stacked_widget.addWidget(self.other_settings_page)
        main_layout.addWidget(self.stacked_widget, 1)

        self.stacked_widget.currentChanged.connect(self.on_page_changed)
        self._connect_signals()

    def _set_stylesheet(self):
        """ 设置全局 QSS 样式表。 """
        primary_color = "#4ACBD6"
        primary_hover_color = "#43b6c0"
        stop_button_color = "#4F46E5"
        stop_button_hover_color = "#4338CA"
        dark_sidebar_color = "#2E2E2E"
        dark_sidebar_hover_color = "#3f3f3f"
        background_color = "#F8F9FA"
        card_bg_color = "#FFFFFF"
        border_color = "#DEE2E6"
        text_color = "#212529"
        secondary_text_color = "#6C757D"

        down_arrow_path = resource_path('static/down-arrow.png').replace('\\', '/')
        yes_path = resource_path('static/yes.png').replace('\\', '/')
        self.setStyleSheet(f"""
            QWidget {{ color: {text_color}; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; background-color: {background_color}; }}
            QFrame#card {{ background-color: {card_bg_color}; border: 1px solid {border_color}; border-radius: 6px; }}
            QLabel {{ font-size: 12px; background-color: transparent; }}
            QCheckBox {{ font-size: 12px; background-color: transparent; }}
            QLabel#titleLabel {{ font-size: 18px; font-weight: 600; color: {text_color}; padding-bottom: 4px; }}
            QLabel#cardTitle {{ font-size: 13px; font-weight: 600; color: {text_color}; }}
            QLineEdit, QComboBox {{ background-color: {card_bg_color}; border: 1px solid {border_color}; border-radius: 5px; padding: 5px; font-size: 12px; }}
            QLineEdit:focus, QComboBox:focus {{ border-color: {primary_color}; }}
            QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 18px; border-left-width: 1px; border-left-color: {border_color}; border-left-style: solid; border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}
            QComboBox::down-arrow {{ image: url({down_arrow_path}); }}
            QTableWidget {{ background-color: {card_bg_color}; border: none; gridline-color: {border_color}; font-size: 12px; alternate-background-color: #FAFBFC; selection-background-color: #E6E6FA; selection-color: {text_color}; }}
            QTableWidget::item {{ padding: 7px 8px; border-bottom: 1px solid #F1F3F5; }}
            QTableWidget::item:selected {{ background-color: #E9EBF8; }}
            QTableWidget::item:focus {{ outline: none; }}
            QHeaderView::section {{ background-color: #FAFBFC; padding: 6px; border: none; border-bottom: 1px solid {border_color}; font-weight: 600; font-size: 12px; }}
            QPushButton {{ background-color: {primary_color}; color: #fff; border: none; padding: 6px 12px; border-radius: 5px; font-size: 12px; font-weight: 500; min-height: 16px; }}
            QPushButton:hover {{ background-color: {primary_hover_color}; }}
            QPushButton:disabled {{ background-color: #E9ECEF; color: {secondary_text_color}; }}
            QPushButton#stopButton {{ background-color: {stop_button_color}; }}
            QPushButton#stopButton:hover {{ background-color: {stop_button_hover_color}; }}
            QPushButton#iconButton, QPushButton#iconTextButton {{ background-color: transparent; border: none; padding: 4px; }}
            QPushButton#iconTextButton {{ color: {secondary_text_color}; font-size: 12px; }}
            QPushButton#iconButton:hover, QPushButton#iconTextButton:hover {{ background-color: transparent; border-radius: 4px; }}
            QPushButton#subtleTextButton {{ background-color: transparent; color: {secondary_text_color}; font-size: 12px; border: 1px solid {border_color}; padding: 3px 8px; border-radius: 4px; }}
            QPushButton#subtleTextButton:hover {{ background-color: #E9ECEF; border-color: #ADB5BD; }}
            QFrame#leftPanel {{ background-color: {dark_sidebar_color}; border-right: 1px solid #252525; }}
            QPushButton#sideBarButton {{ background-color: transparent; color: #D0D0D0; text-align: center; padding: 8px 5px; font-weight: 600; border: none; border-radius: 5px; margin: 0px 4px; }}
            QPushButton#sideBarButton:hover {{ background-color: {dark_sidebar_hover_color}; }}
            QProgressBar {{ border: 1px solid {border_color}; border-radius: 5px; text-align: center; background-color: #E9ECEF; color: {secondary_text_color}; font-size: 12px; }}
            QProgressBar::chunk {{ background-color: {primary_color}; border-radius: 5px; }}
            QCheckBox::indicator {{ width: 12px; height: 12px; border: 1px solid #DEE2E6; border-radius: 3px; padding: 1px; }}
            QCheckBox::indicator:hover {{ border: 1px solid #4ACBD6; }}
            QCheckBox::indicator:checked {{ image: url({yes_path}); }}
            QTableView::indicator {{ width: 10px; height: 10px; border: 1px solid #8A8A8A; border-radius: 2px; padding: 1px; }}
            QTableView::indicator:checked {{ image: url({yes_path}) }}
            QScrollBar:vertical {{border: none;background-color: #F1F3F5; width: 8px;margin: 0px 0px 0px 0px;}}
            QScrollBar:horizontal {{ border: none; background-color: #F1F3F5; height: 8px; margin: 0px 0px 0px 0px; }}
            QScrollBar::handle {{ background-color: #CED4DA; border-radius: 4px; }}
            QScrollBar::handle:hover {{ background-color: #ADB5BD; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ border: none; background: none; height: 0px; width: 0px; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
            QHeaderView::section:last {{ color: #565656; font-size: 20px; font-weight: bold; }}
            QHeaderView::section:last:hover {{ background-color: #E9ECEF; color: #4ACBD6; }}
        """)

    def _create_left_panel(self):
        """ 创建左侧的图标按钮侧边栏。 """
        left_panel = QFrame(objectName="leftPanel")
        left_panel.setFixedWidth(50)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 12, 5, 12)
        left_layout.setSpacing(8)

        self.server_button = QPushButton("", objectName="sideBarButton")
        self.server_button.setIcon(QIcon(resource_path("static/serial1.png")))
        self.server_button.setIconSize(QSize(24, 24))
        self.server_button.setToolTip("启动/停止Server")
        self.server_button.clicked.connect(self.toggle_manual_server)

        self.params_icon = QIcon(resource_path("static/params-icon.png"))
        self.home_icon = QIcon(resource_path("static/home.png"))
        self.other_settings_button = QPushButton("", objectName="sideBarButton")
        self.other_settings_button.setIcon(self.params_icon)
        self.other_settings_button.setIconSize(QSize(24, 24))
        self.other_settings_button.setToolTip("其他参数")
        self.other_settings_button.clicked.connect(self.toggle_other_settings_page)

        report_button = QPushButton("", objectName="sideBarButton")
        report_button.setIcon(QIcon(resource_path("static/report-icon.png")))
        report_button.setIconSize(QSize(24, 24))
        report_button.setToolTip("打开报告")
        report_button.clicked.connect(self.open_last_report)

        settings_button = QPushButton("", objectName="sideBarButton")
        settings_button.setIcon(QIcon(resource_path("static/settings-icon.png")))
        settings_button.setIconSize(QSize(24, 24))
        settings_button.setToolTip("设置")
        settings_button.clicked.connect(self.open_settings_dialog)

        left_layout.addWidget(self.server_button)

        left_layout.addStretch()
        left_layout.addWidget(self.other_settings_button)
        left_layout.addWidget(report_button)
        left_layout.addWidget(settings_button)

        return left_panel

    def _create_main_page(self):
        """ 创建主内容页面。 """
        main_page = QWidget()
        right_layout = QVBoxLayout(main_page)
        right_layout.setContentsMargins(15, 10, 15, 10)
        right_layout.setSpacing(10)

        title = QLabel("Automa自动化工具", objectName="titleLabel")
        right_layout.addWidget(title)

        # 机型信息卡片
        self.model_info_card = QFrame(objectName="card")
        model_info_layout = QVBoxLayout(self.model_info_card)
        model_info_layout.setSpacing(10)
        model_info_layout.setContentsMargins(10, 8, 10, 10)
        model_info_layout.addWidget(QLabel("机型信息", objectName="cardTitle"))
        model_row1_layout = QHBoxLayout()
        model_row1_layout.addWidget(QLabel("机型名称:"))
        self.model_name_entry = QLineEdit()
        model_row1_layout.addWidget(self.model_name_entry)
        model_row1_layout.addSpacing(20)
        model_row1_layout.addWidget(QLabel("软件版本:"))
        self.model_version_entry = QLineEdit()
        model_row1_layout.addWidget(self.model_version_entry)
        model_info_layout.addLayout(model_row1_layout)
        model_row2_layout = QHBoxLayout()
        model_row2_layout.addWidget(QLabel("软件路径:"))
        self.img_file_entry = ClickableLineEdit()
        self.img_file_entry.setReadOnly(True)
        self.img_file_entry.setPlaceholderText("点击选择文件夹...")

        img_entry_layout = QHBoxLayout(self.img_file_entry)
        img_entry_layout.setContentsMargins(0, 0, 4, 0)
        self.img_file_clear_button = QPushButton(QIcon(resource_path("static/clear.png")), "")
        self.img_file_clear_button.setFixedSize(22, 22)
        self.img_file_clear_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.img_file_clear_button.setStyleSheet(
            "QPushButton { border: none; border-radius: 11px; padding: 0; background-color: transparent; } "
            "QPushButton:hover { background-color: #E5E7EB; }"
        )
        img_entry_layout.addStretch()
        img_entry_layout.addWidget(self.img_file_clear_button)

        model_row2_layout.addWidget(self.img_file_entry)
        model_info_layout.addLayout(model_row2_layout)
        right_layout.addWidget(self.model_info_card)

        # 参数设置卡片
        self.settings_card = QFrame(objectName="card")
        settings_layout = QVBoxLayout(self.settings_card)
        settings_layout.setSpacing(10)
        settings_layout.setContentsMargins(10, 8, 10, 10)
        settings_layout.addWidget(QLabel("参数设置", objectName="cardTitle"))
        params_row1_layout = QHBoxLayout()

        params_row1_layout.addWidget(QLabel("串口端口:"))
        self.default_serial_combo = QComboBox()
        self.default_serial_combo.setMinimumWidth(120)
        params_row1_layout.addWidget(self.default_serial_combo, 1)
        params_row1_layout.addSpacing(20)
        params_row1_layout.addWidget(QLabel("有线网卡:"))
        self.wired_adapter_combo = QComboBox()
        params_row1_layout.addWidget(self.wired_adapter_combo, 1)
        params_row1_layout.addSpacing(20)
        params_row1_layout.addWidget(QLabel("无线网卡:"))
        wireless_container = QWidget()
        wireless_layout = QGridLayout(wireless_container)
        wireless_layout.setContentsMargins(0, 0, 0, 0)
        self.wireless_adapter_combo = QComboBox()
        self.adapter_support_6g_checkbox = QCheckBox("支持6G")
        self.adapter_support_6g_checkbox.setStyleSheet("background-color: white; margin-right: 25px; padding-left: 2px")
        wireless_layout.addWidget(self.wireless_adapter_combo, 0, 0)
        wireless_layout.addWidget(self.adapter_support_6g_checkbox, 0, 0, Qt.AlignmentFlag.AlignRight)
        params_row1_layout.addWidget(wireless_container, 1)
        settings_layout.addLayout(params_row1_layout)
        right_layout.addWidget(self.settings_card)
        self.populate_default_serials()
        self.populate_network_interfaces(self.wired_adapter_combo)
        self.populate_network_interfaces(self.wireless_adapter_combo)

        # 脚本列表卡片
        scripts_card = QFrame(objectName="card")
        scripts_layout = QVBoxLayout(scripts_card)
        scripts_layout.setSpacing(6)
        scripts_layout.setContentsMargins(10, 10, 10, 10)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("脚本列表", objectName="cardTitle"))
        controls_layout.addStretch()

        self.search_scripts_entry = QLineEdit()
        self.search_scripts_entry.setPlaceholderText("搜索case...")
        self.search_scripts_entry.setFixedWidth(180)
        controls_layout.addWidget(self.search_scripts_entry)

        self.select_all_checkbox = QCheckBox("全选")
        self.select_all_checkbox.setTristate(True)
        controls_layout.addWidget(self.select_all_checkbox)
        scripts_layout.addLayout(controls_layout)

        self.scripts_table = QTableWidget()
        self.scripts_table.setItemDelegate(NoFocusDelegate(self.scripts_table))
        self.scripts_table.setColumnCount(4)
        self.scripts_table.setHorizontalHeaderLabels(["选择", "脚本名称", "描述", "＋"])
        self.scripts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.scripts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.scripts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.scripts_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.scripts_table.setColumnWidth(3, 50)
        self.scripts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.scripts_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.scripts_table.setShowGrid(False)
        self.scripts_table.setAlternatingRowColors(True)
        self.scripts_table.setMinimumHeight(260)

        self.scripts_table.verticalHeader().setDefaultSectionSize(34)
        self.scripts_table.verticalHeader().setVisible(False)
        self.scripts_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scripts_layout.addWidget(self.scripts_table, 1)
        right_layout.addWidget(scripts_card, 1)

        # 执行控制卡片
        control_card = QFrame(objectName="card")
        control_layout = QVBoxLayout(control_card)
        control_layout.setSpacing(10)
        control_layout.setContentsMargins(10, 8, 10, 10)
        control_layout.addWidget(QLabel("执行控制", objectName="cardTitle"))
        status_layout = QHBoxLayout()
        self.status_label = QLabel("准备就绪")
        self.status_label.setMinimumWidth(1)
        status_layout.addWidget(self.status_label, 1)
        self.timer_label = QLabel("执行时间: 00:00:00")
        self.timer_label.setVisible(False)
        status_layout.addWidget(self.timer_label)
        status_layout.addSpacing(20)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar, 1)
        control_layout.addLayout(status_layout)

        self.log_label = QLineEdit()
        self.log_label.setReadOnly(True)
        self.log_label.setPlaceholderText("等待实时日志输出...")
        self.log_label.setVisible(False)
        control_layout.addWidget(self.log_label)

        self.action_button = QPushButton("开始执行")
        control_layout.addWidget(self.action_button)
        right_layout.addWidget(control_card)

        return main_page

    def _update_img_clear_button_visibility(self, text):
        """ 根据输入框内容显示或隐藏软件路径的清除按钮 """
        self.img_file_clear_button.setVisible(bool(text))
        if bool(text):
            self.img_file_entry.setTextMargins(0, 0, 28, 0)
        else:
            self.img_file_entry.setTextMargins(0, 0, 0, 0)

    def _connect_signals(self):
        """ 集中连接所有UI组件的信号和槽。 """
        self.model_name_entry.textChanged.connect(self.save_settings_silently)
        self.model_version_entry.textChanged.connect(self.save_settings_silently)
        self.img_file_entry.textChanged.connect(self.save_settings_silently)
        self.img_file_entry.clicked.connect(self.browse_img_file_path)
        self.img_file_entry.textChanged.connect(self._update_img_clear_button_visibility)
        self.img_file_clear_button.clicked.connect(self.img_file_entry.clear)
        self.default_serial_combo.currentTextChanged.connect(self.save_settings_silently)
        self.wired_adapter_combo.currentTextChanged.connect(self.save_settings_silently)
        self.wireless_adapter_combo.currentTextChanged.connect(self.save_settings_silently)
        self.adapter_support_6g_checkbox.stateChanged.connect(self.save_settings_silently)
        self.search_scripts_entry.textChanged.connect(self.filter_scripts)
        self.select_all_checkbox.stateChanged.connect(self.toggle_select_all)
        self.action_button.clicked.connect(self.toggle_runner)
        self.scripts_table.horizontalHeader().sectionClicked.connect(self.on_header_add_clicked)
        self._connect_scripts_table_signal()

    def _disconnect_scripts_table_signal(self):
        """安全地断开脚本表格的 itemChanged 信号，避免重复断开带来的警告。"""
        if not self._scripts_table_signal_connected:
            return
        try:
            self.scripts_table.itemChanged.disconnect(self.on_scripts_table_item_changed)
        except (TypeError, RuntimeError):
            pass
        self._scripts_table_signal_connected = False

    def _connect_scripts_table_signal(self):
        """仅在未连接时再连接脚本表格的 itemChanged 信号。"""
        if self._scripts_table_signal_connected:
            return
        self.scripts_table.itemChanged.connect(self.on_scripts_table_item_changed)
        self._scripts_table_signal_connected = True

    def on_page_changed(self, index):
        """ 当页面切换时，改变侧边栏参数按钮的图标和提示。 """
        if index == 1:  # 切换到其他参数页面
            self.other_settings_button.setIcon(self.home_icon)
            self.other_settings_button.setToolTip("返回主页")
        else:  # 切换到主页
            self.other_settings_button.setIcon(self.params_icon)
            self.other_settings_button.setToolTip("其他参数设置")

    def toggle_other_settings_page(self):
        """ 切换主页和“其他参数”设置页面。 """
        current_index = self.stacked_widget.currentIndex()
        self.stacked_widget.setCurrentIndex(1 - current_index)

    def browse_img_file_path(self):
        """ 打开文件夹选择对话框以选择软件路径。 """
        directory = QFileDialog.getExistingDirectory(self, "选择软件文件夹")
        if directory:
            self.img_file_entry.setText(directory.replace('/',"\\"))

    def filter_scripts(self):
        """ 根据搜索框中的文本过滤脚本列表。 """
        search_text = self.search_scripts_entry.text().lower()
        for i in range(self.scripts_table.rowCount()):
            item = self.scripts_table.item(i, 1)
            if item:
                is_match = search_text in item.text().lower()
                self.scripts_table.setRowHidden(i, not is_match)
        self.update_select_all_checkbox()

    def update_select_all_checkbox(self):
        """ 根据当前可见的脚本勾选情况同步全选复选框状态。 """
        if not hasattr(self, "select_all_checkbox"):
            return

        visible_rows = [
            i for i in range(self.scripts_table.rowCount())
            if not self.scripts_table.isRowHidden(i)
        ]
        if not visible_rows:
            target_state = Qt.CheckState.Unchecked
        else:
            checked_count = 0
            for row in visible_rows:
                item = self.scripts_table.item(row, 0)
                if item and item.checkState() == Qt.CheckState.Checked:
                    checked_count += 1
            if checked_count == len(visible_rows):
                target_state = Qt.CheckState.Checked
            elif checked_count == 0:
                target_state = Qt.CheckState.Unchecked
            else:
                target_state = Qt.CheckState.PartiallyChecked

        signals_were_blocked = self.select_all_checkbox.blockSignals(True)
        self.select_all_checkbox.setCheckState(target_state)
        self.select_all_checkbox.blockSignals(signals_were_blocked)

    def on_scripts_table_item_changed(self, item):
        """ 监听脚本勾选变化以同步全选状态并保存配置。 """
        if item and item.column() == 0:
            self.update_select_all_checkbox()
        self.save_settings_silently()

    def populate_default_serials(self):
        """ 填充串口下拉框的选项。 """
        self.default_serial_combo.addItem("不使用")
        try:
            ports = serial.tools.list_ports.comports()
            for port in sorted(ports):
                self.default_serial_combo.addItem(port.device)
        except Exception as e:
            print(f"无法获取串口列表: {e}")

    def populate_network_interfaces(self, combo_box):
        """ 填充网卡下拉框的选项。 """
        combo_box.addItem("不使用")
        try:
            addrs = psutil.net_if_addrs()
            for name in sorted(addrs.keys()):
                combo_box.addItem(name)
        except Exception as e:
            print(f"无法获取网络接口列表: {e}")
            combo_box.addItem("获取失败")

    def update_execution_time(self):
        """ 每秒更新执行计时器标签。 """
        if self.start_time > 0:
            elapsed_seconds = int(time.time() - self.start_time)
            hours, remainder = divmod(elapsed_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.timer_label.setText(f"执行时间: {hours:02}:{minutes:02}:{seconds:02}")

    def update_log_label(self, log_line):
        """ 在UI上更新显示的实时日志行。 """
        self.log_label.setText(log_line)
        self.log_label.setCursorPosition(0)

    def load_settings(self):
        """ 从 setting.json 文件加载配置。 """
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.status_label.setText(f"加载配置文件失败: {e}，将使用默认设置。")
                self.settings = {}
        else:
            self.settings = {}

        if "use_default_python" not in self.settings:
            self.settings["use_default_python"] = True

        self.populate_ui_from_settings()
        # 如果配置文件不存在或为空，则保存一次当前默认设置
        if not os.path.exists(self.settings_path) or not self.settings:
            self.save_settings_silently()

    def populate_ui_from_settings(self):
        """ 根据加载的配置数据填充UI界面。 """
        # 暂时断开所有会触发保存的信号，以避免在填充时循环调用
        all_widgets = [self.model_name_entry, self.model_version_entry, self.img_file_entry]
        for widget in all_widgets:
            widget.textChanged.disconnect(self.save_settings_silently)

        all_combos = [self.default_serial_combo, self.wired_adapter_combo, self.wireless_adapter_combo]
        for combo in all_combos:
            combo.currentTextChanged.disconnect(self.save_settings_silently)

        self.adapter_support_6g_checkbox.stateChanged.disconnect(self.save_settings_silently)
        self._disconnect_scripts_table_signal()

        # 填充UI控件
        self.model_name_entry.setText(self.settings.get("model_name", "Archer BE800(US) 1.0"))
        self.model_version_entry.setText(self.settings.get("model_version", ""))
        img_path = self.settings.get("model_path", "") if os.path.exists(self.settings.get("model_path", "")) else ""
        self.img_file_entry.setText(img_path)
        self._update_img_clear_button_visibility(img_path)
        self.adapter_support_6g_checkbox.setChecked(self.settings.get("adapter_support_6g", False))

        def set_combo_value(combo, key, default="不使用"):
            saved_value = self.settings.get(key, default)
            if combo.findText(saved_value) != -1:
                combo.setCurrentText(saved_value)
            else:
                combo.setCurrentText(default)

        set_combo_value(self.default_serial_combo, "default_serial")
        set_combo_value(self.wired_adapter_combo, "wired_adapter")
        set_combo_value(self.wireless_adapter_combo, "wireless_adapter")
        self.refresh_script_list()
        self.other_settings_page.load_other_settings()

        # 重新连接信号
        for widget in all_widgets:
            widget.textChanged.connect(self.save_settings_silently)
        for combo in all_combos:
            combo.currentTextChanged.connect(self.save_settings_silently)
        self.adapter_support_6g_checkbox.stateChanged.connect(self.save_settings_silently)
        self._connect_scripts_table_signal()

    def _get_main_page_settings(self):
        """ 从UI控件中收集主页面的所有设置项。 """
        selected_scripts = []
        for i in range(self.scripts_table.rowCount()):
            if self.scripts_table.item(i, 0).checkState() == Qt.CheckState.Checked:
                selected_scripts.append(self.scripts_table.item(i, 1).text())

        def get_combo_value(combo):
            text = combo.currentText()
            return "" if text == "不使用" else text

        return {
            "model_name": self.model_name_entry.text(),
            "model_version": self.model_version_entry.text(),
            "model_path": self.img_file_entry.text(),
            "default_serial": get_combo_value(self.default_serial_combo),
            "wired_adapter": get_combo_value(self.wired_adapter_combo),
            "wireless_adapter": get_combo_value(self.wireless_adapter_combo),
            "adapter_support_6g": self.adapter_support_6g_checkbox.isChecked(),
            "selected_scripts": selected_scripts
        }

    def save_settings(self):
        """ 将当前的所有UI设置保存到 setting.json 文件。 """
        main_page_settings = self._get_main_page_settings()
        self.settings.update(main_page_settings)

        try:
            full_path = os.path.abspath(self.settings_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except (IOError, TypeError) as e:
            print(f"保存设置失败: {e}")

    def save_settings_silently(self):
        """ 在后台静默保存设置，通常由UI事件（如文本更改）触发。 """
        self.save_settings()

    def toggle_runner(self):
        """ 根据当前状态启动或停止测试执行。 """
        if self.runner_thread and self.runner_thread.isRunning():
            self.stop_runner()
        else:
            self.start_runner()

    def select_python_executable(self):
        """
        选择并返回将用于运行的Python解释器路径，实现了缓存和回退逻辑。
        """
        if self.runtime_python_executable:
            return self.runtime_python_executable

        base_python = self.resolved_python_executable
        if not base_python:
            if self.is_using_portable_python:
                base_python = find_python_executable(allow_system_search=False, include_portable=True)
            else:
                manual_candidate = _normalize_python_path(self.settings.get("python_path"))
                base_python = manual_candidate or find_python_executable(
                    None, allow_system_search=True, include_portable=False
                )
        
        if base_python:
            self.resolved_python_executable = base_python
            self.runtime_python_executable = base_python
            return base_python
        
        return None

    def toggle_manual_server(self):
        """手动启动或停止服务。"""
        if self.server_process and self.server_process.poll() is None:
            self._stop_server()
        else:
            self._start_server(is_manual=True)

    def _start_server(self, is_manual=False):
        """同步启动服务，内置串口检查和延时。"""
        selected_port = self.default_serial_combo.currentText()
        if selected_port and selected_port != "不使用":
            self.status_label.setText(f"正在检查串口 {selected_port}...")
            QApplication.processEvents()  # Update UI
            try:
                ser = serial.Serial(selected_port)
                ser.close()
            except serial.SerialException:
                message = f"错误: 串口 '{selected_port}' 已被占用或无法访问。"
                self.reset_ui_and_msg(message)
                QMessageBox.warning(self, "端口错误", message)
                return False

        self.status_label.setText("正在启动服务...")
        QApplication.processEvents()
        python_executable = self.select_python_executable()
        if not python_executable:
            self.reset_ui_and_msg("未找到有效的 Python 环境，无法启动服务。")
            QMessageBox.critical(self, "环境错误", "未能确定Python环境，请在设置中检查或重启程序。")
            return False

        cmd = [python_executable, "-m", "tp_autotest.server"]
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self.server_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding='utf-8', errors='replace', creationflags=creation_flags,
                shell=False, bufsize=1
            )
            time.sleep(0.5)
            if self.server_process.poll() is not None:
                raise RuntimeError("服务进程启动后立即退出，请检查环境。")
            if self.default_serial_combo.currentText() != "不使用":
                webbrowser.open("http://127.0.0.1")
            self.server_started_by_user = is_manual
            self.status_label.setText("串口服务已启动")
            self.server_button.setIcon(QIcon(resource_path("static/serial2.png")))
            return True

        except Exception as e:
            self.server_process = None
            self.reset_ui_and_msg(f"启动服务失败: {e}")
            traceback.print_exc()
            return False

    def _stop_server(self):
        """停止服务进程。"""
        if self.server_process and self.server_process.poll() is None:
            self.status_label.setText("正在停止串口服务...")
            try:
                pid = self.server_process.pid
                command = f"taskkill /F /T /PID {pid}"
                subprocess.run(
                    command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.log_label.setText(f"服务进程 (PID: {pid}) 已被终止。")
            except Exception as e:
                self.log_label.setText(f"停止服务时发生意外错误: {e}")
                try:
                    self.server_process.kill()
                except:
                    pass
        self.server_process = None
        self.server_started_by_user = False
        self.status_label.setText("串口服务已停止")
        self.server_button.setIcon(QIcon(resource_path("static/serial1.png")))

    def start_runner(self):
        """
        启动测试的入口函数。
        负责处理先决条件检查、权限提升和环境设置。
        """
        self.save_settings_silently()

        # 检查是否需要管理员权限
        needs_admin = False
        self.is_using_portable_python = self.settings.get("use_default_python", True)

        if not self.is_using_portable_python:
            manual_path = self.settings.get("python_path", "")
            normalized_manual = _normalize_python_path(manual_path)
            if not normalized_manual:
                auto_candidate = find_python_executable(None, allow_system_search=True, include_portable=False)
                if auto_candidate:
                    self.settings["python_path"] = auto_candidate
                    self.save_settings()
                    normalized_manual = auto_candidate
                    self.status_label.setText("已自动识别系统中的 Python 解释器。")
                else:
                    self.reset_ui_and_msg("请在设置中选择有效的 Python 解释器。")
                    QMessageBox.warning(self, "环境设置", "未检测到有效的 Python 解释器，请在“设置”中指定后再试。")
                    return
            else:
                self.settings["python_path"] = normalized_manual
                self.save_settings()

        if self.is_using_portable_python:
            if not find_python_executable(allow_system_search=False, include_portable=True) and not self.is_restarting_after_install:
                needs_admin = True  # 需要安装或修复便携 Python
        if self.wireless_adapter_combo.currentText() not in ["", "不使用"]:
            needs_admin = True  # 操作网卡需要权限
        if "\\Automa" not in os.environ.get('PATH', '').lower():
            needs_admin = True  # 设置环境变量需要权限

        # 如果需要且当前不是管理员，则尝试提权并重启
        if needs_admin and not is_admin():
            self.status_label.setText("需要管理员权限，正在尝试提权...")
            QApplication.processEvents()
            try:
                # 使用管理员权限重新启动脚本，并附带 '--autostart' 标志以便自动执行
                params = " ".join([arg for arg in sys.argv if arg != '--post-install']) + " --autostart"
                ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
                sys.exit()  # 退出当前的非管理员进程
            except Exception as e:
                self.reset_ui_and_msg(f"提权失败: {e}")
                QMessageBox.critical(self, "错误", f"需要管理员权限才能继续。\n提权失败: {e}")
                return

        # 在每次执行前重置已解析的 Python 环境，待安装流程完成后再赋值
        self.resolved_python_executable = None
        self.runtime_python_executable = None

        # 开始环境与依赖的设置流程
        self.action_button.setEnabled(False)
        self.status_label.setText("正在检查环境，请稍候...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_label.setVisible(True)
        self.log_label.clear()
        QApplication.processEvents()

        required_packages = [
            "psutil", "pyserial", "Jinja2", "pywifi", "airtest",
            "selenium==4.35.0", "paddlepaddle==2.6.1", "paddleocr==2.7.3", "numpy==1.26.4",
            f"source/tp_autotest=={MODULE_VERSION}"
        ]
        self.setup_thread = EnvironmentAndDependenciesThread(
            required_packages,
            use_default_python=self.is_using_portable_python,
            user_python_path=self.settings.get("python_path")
        )
        self.setup_thread.status_update.connect(self.status_label.setText)
        self.setup_thread.log_update.connect(self.update_log_label)
        self.setup_thread.progress_update.connect(self.progress_bar.setValue)
        self.setup_thread.finished.connect(self.on_setup_finished)
        self.setup_thread.start()

    def on_setup_finished(self, success, message):
        """
        环境和依赖项设置完成时的回调函数。
        如果成功，则继续进行最终的硬件（串口）检查。
        """
        if not success:
            self.reset_ui_and_msg(message)
            QMessageBox.critical(self, "环境准备失败", message)
            return

        # 缓存当前线程解析到的 Python 可执行文件
        if self.setup_thread and getattr(self.setup_thread, "python_exe", None):
            self.resolved_python_executable = self.setup_thread.python_exe
            runtime_candidate = getattr(self.setup_thread, "runtime_python_exe", None)
            self.runtime_python_executable = runtime_candidate or self.resolved_python_executable

        # 环境检查通过后，直接进入测试执行流程
        self._proceed_with_execution()

    def _proceed_with_execution(self):
        """ 在所有检查通过后，正式启动测试执行线程。 """
        # 检查服务是否已在运行，如果未运行则尝试启动
        server_was_running = self.server_process and self.server_process.poll() is None
        if not server_was_running:
            if not self._start_server(is_manual=False):
                self.reset_ui_and_msg("自动启动Serial服务失败，测试中止。")
                return

        current_settings = self.settings.copy()
        start_timestamp = time.time()
        current_settings["start_time"] = start_timestamp
        selected_cases = current_settings.get("selected_scripts", [])

        if not selected_cases:
            self.reset_ui_and_msg("请至少选择一个脚本。")
            if not self.server_started_by_user:
                self._stop_server()
            return

        # 更新UI为“运行中”状态
        self.action_button.setText("停止运行")
        self.action_button.setObjectName("stopButton")
        self.action_button.style().polish(self.action_button)
        self.action_button.setEnabled(True)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.start_time = start_timestamp
        self.timer_label.setText("执行时间: 00:00:00")
        self.timer_label.setVisible(True)
        self.execution_timer.start(1000)

        self.progress_bar.setValue(1)

        self.log_label.clear()
        self.log_label.setVisible(True)

        python_executable = self.select_python_executable()
        if not python_executable:
            self.reset_ui_and_msg("未找到 Python 环境，无法执行用例。")
            QMessageBox.critical(self, "环境错误", "未找到可用的 Python 环境。")
            if not self.server_started_by_user:
                self._stop_server()
            return

        self.runner_thread = RunnerThread(selected_cases, current_settings, python_executable)
        self.runner_thread.status_update.connect(self.status_label.setText)
        self.runner_thread.progress_update.connect(self.progress_bar.setValue)
        self.runner_thread.finished.connect(self.on_runner_finished)
        self.runner_thread.log_update.connect(self.update_log_label)
        self.runner_thread.start()

    def stop_runner(self):
        """ 停止正在运行的测试。 """
        if self.runner_thread:
            self.runner_thread.stop()

        # 如果服务是为本次测试自动启动的，则关闭它
        if not self.server_started_by_user:
            self._stop_server()

        self.action_button.setText("正在停止...")
        self.action_button.setEnabled(False)
        self.execution_timer.stop()

    def reset_ui_and_msg(self, message):
        """ 在启动失败或测试结束后，重置UI到初始状态。 """
        self.status_label.setText(message)
        self.action_button.setEnabled(True)
        self.action_button.setText("开始执行")
        self.action_button.setObjectName("")
        self.action_button.style().polish(self.action_button)
        self.progress_bar.setVisible(False)
        self.log_label.setVisible(False)
        self.timer_label.setVisible(False)
        self.execution_timer.stop()

    def on_runner_finished(self, report_path):
        """ 测试完成后恢复UI状态，并自动打开报告。 """
        # 如果服务是为本次测试自动启动的，则关闭它
        if not self.server_started_by_user:
            self._stop_server()

        self.action_button.setText("开始执行")
        self.action_button.setObjectName("")
        self.action_button.style().polish(self.action_button)
        self.action_button.setEnabled(True)
        self.execution_timer.stop()
        self.progress_bar.setVisible(False)
        self.log_label.setVisible(False)
        self.start_time = 0
        if report_path:
            webbrowser.open(report_path)

    def toggle_select_all(self, state):
        """ 全选或全不选所有可见的脚本。 """
        self._disconnect_scripts_table_signal()
        check_state = Qt.CheckState.Checked if state > 0 else Qt.CheckState.Unchecked
        for i in range(self.scripts_table.rowCount()):
            if not self.scripts_table.isRowHidden(i):
                self.scripts_table.item(i, 0).setCheckState(check_state)
        self._connect_scripts_table_signal()
        self.save_settings_silently()
        self.update_select_all_checkbox()

    def open_last_report(self):
        """ 在浏览器中打开最新的报告文件。 """
        report_path = os.path.join(get_report_dir(), "result.html")
        if os.path.exists(report_path):
            url = 'file:///' + os.path.realpath(report_path).replace('\\', '/')
            webbrowser.open(url)
            self.status_label.setText(f"已打开报告: {report_path}")
        else:
            self.status_label.setText("未找到报告文件，请先运行测试。")

    def open_settings_dialog(self):
        """ 打开设置对话框。 """
        dialog = SettingsDialog(self)
        dialog.exec()

    def import_cases(self):
        """ 从 ZIP 压缩包导入一个或多个测试用例。 """
        file_path, _ = QFileDialog.getOpenFileName(self, "选择要导入的ZIP压缩包", "", "ZIP Files (*.zip)")
        if not file_path:
            return

        dest_dir = os.path.join(os.getcwd(), "case")
        os.makedirs(dest_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                top_level_dirs = set()
                # 预先扫描以检查是否存在同名文件夹
                for member in zip_ref.infolist():
                    # 尝试解决中文文件名乱码问题
                    if member.flag_bits & 0x800:
                        filename = member.filename
                    else:
                        filename = member.filename.encode('cp437').decode('gbk')
                    path_parts = os.path.normpath(filename).split(os.sep)
                    if path_parts[0]:
                        top_level_dirs.add(path_parts[0])

                for dir_name in top_level_dirs:
                    if os.path.exists(os.path.join(dest_dir, dir_name)):
                        QMessageBox.warning(self, "导入失败", f"名为 '{dir_name}' 的用例已存在，请先删除。")
                        return

                # 解压文件
                for member in zip_ref.infolist():
                    if member.flag_bits & 0x800:
                        filename = member.filename
                    else:
                        filename = member.filename.encode('cp437').decode('gbk')
                    target_path = os.path.join(dest_dir, filename)

                    if member.is_dir():
                        if not os.path.exists(target_path):
                            os.makedirs(target_path)
                    else:
                        parent_dir = os.path.dirname(target_path)
                        if not os.path.exists(parent_dir):
                            os.makedirs(parent_dir)

                        with open(target_path, 'wb') as f:
                            f.write(zip_ref.read(member.filename))

            self.status_label.setText(f"已从 {os.path.basename(file_path)} 成功导入用例。")
            self.refresh_script_list()

        except Exception as e:
            self.status_label.setText(f"解压导入失败: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"从ZIP文件导入时发生错误: {e}")

    def delete_case(self, case_name):
        """ 删除指定的测试用例文件夹。 """
        confirm_delete = self.dont_confirm

        if not confirm_delete:
            msg_box = QMessageBox(self)
            msg_box.setStyleSheet(f"""
                QMessageBox {{ font-size: 12px; }}
                QPushButton {{ background-color: #4F46E5; color: #fff; border: none; padding: 3px 10px; border-radius: 4px; font-size: 12px; min-width: 60px; }}
                QPushButton:hover {{ background-color: #4338CA; }}
                QCheckBox {{ font-size: 12px; }}
            """)
            msg_box.setWindowTitle("删除确认")
            msg_box.setText(f"是否永久删除脚本 '{case_name}' ?           \u00A0\n")
            msg_box.setIcon(QMessageBox.Icon.Warning)
            yes_button = msg_box.addButton("删除", QMessageBox.ButtonRole.YesRole)
            msg_box.addButton("取消", QMessageBox.ButtonRole.NoRole)
            dont_show_again_checkbox = QCheckBox("不再提示")
            # 将复选框添加到对话框布局中
            msg_box.layout().addWidget(dont_show_again_checkbox, 2, 0, Qt.AlignmentFlag.AlignBottom)

            msg_box.exec()

            if msg_box.clickedButton() != yes_button:
                return  # 用户取消了操作

            if dont_show_again_checkbox.isChecked():
                self.dont_confirm = True

        try:
            case_path = os.path.join(os.getcwd(), "case", case_name)
            if os.path.isdir(case_path):
                shutil.rmtree(case_path)
                self.status_label.setText(f"已删除用例: '{case_name}'")
                self.refresh_script_list()
                self.scripts_table.clearSelection()
            else:
                self.status_label.setText(f"删除失败: 目录 '{case_name}' 未找到。")
        except Exception as e:
            self.status_label.setText(f"删除 '{case_name}' 时出错: {e}")
            QMessageBox.critical(self, "删除失败", f"删除用例时发生错误: {e}")

    def on_header_add_clicked(self, logicalIndex):
        """ 当脚本列表的表头被点击时调用，用于触发导入功能。 """
        # 检查被点击的是否是最后一列（即“+”按钮所在的列）
        if logicalIndex == self.scripts_table.columnCount() - 1:
            self.import_cases()

    def refresh_script_list(self):
        """ 从 'case' 目录重新加载并刷新UI中的脚本列表。 """
        self._disconnect_scripts_table_signal()

        selected_scripts = self.settings.get("selected_scripts", [])
        cases = get_cases()
        self.scripts_table.setRowCount(len(cases))

        for i, case in enumerate(cases):
            # 第0列: 复选框
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check_state = Qt.CheckState.Checked if case in selected_scripts else Qt.CheckState.Unchecked
            check_item.setCheckState(check_state)
            self.scripts_table.setItem(i, 0, check_item)

            # 第1列: 脚本名称
            script_name_item = QTableWidgetItem(case)
            script_name_item.setToolTip(case)
            self.scripts_table.setItem(i, 1, script_name_item)

            # 第2列: 脚本描述
            description = get_script_description(case)
            description_item = QTableWidgetItem(description)
            description_item.setToolTip(description)
            self.scripts_table.setItem(i, 2, description_item)

            # 第3列: 删除按钮
            delete_button = QPushButton()
            delete_button.setIcon(QIcon(resource_path("static/delete.png")))
            delete_button.setObjectName("iconButton")
            delete_button.setToolTip(f"删除 '{case}'")
            delete_button.setFixedSize(24, 24)
            delete_button.setIconSize(QSize(12, 12))
            delete_button.clicked.connect(lambda checked=False, c=case: self.delete_case(c))

            # 使用一个容器Widget来使按钮在单元格中居中
            cell_container = QWidget()
            cell_container.setStyleSheet(f"""
                QWidget {{background-color: transparent; }}
                QToolTip {{background-color: white; color:black; }}
            """)
            cell_layout = QVBoxLayout(cell_container)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell_layout.addWidget(delete_button)

            self.scripts_table.setCellWidget(i, 3, cell_container)

        self.scripts_table.resizeColumnToContents(1)
        # 限制脚本名称列的最大宽度
        if self.scripts_table.columnWidth(1) > 350:
            self.scripts_table.setColumnWidth(1, 350)

        self._connect_scripts_table_signal()
        self.update_select_all_checkbox()
# =====================================================================================================================
# 程序入口
# =====================================================================================================================
def is_admin():
    """ 检查当前脚本是否以管理员权限运行 (仅限Windows)。 """
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())
