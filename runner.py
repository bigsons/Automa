# -*- encoding=utf-8 -*-
import os
import re
import traceback
import subprocess
import webbrowser
import time
import json
import shutil
import argparse
from jinja2 import Environment, FileSystemLoader

serial_server_process = None
serial_server_log_file = None

def get_script_description(case_script):
    """ 从测试脚本文件中提取 __brief__ 描述 """
    try:
        script_name = os.path.splitext(case_script)[0]
        script_path = os.path.join(os.getcwd(), "case", case_script, f"{script_name}.py")
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r'\s*__brief__\s*=\s*["\'](.*?)["\']', content)
                if match:
                    return match.group(1).strip()
    except Exception as e:
        print(f"读取 {case_script} 的 __brief__ 时出错: {e}")
    return "暂无脚本描述"

def start_serial_server():
    """ 启动后台串口服务进程 """
    global serial_server_process, serial_server_log_file
    use_serial = False
    try:
        if os.path.exists("setting.json"):
            with open("setting.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
                if settings.get("default_serial") and settings.get("default_serial") != "不使用":
                    use_serial = True
        if not use_serial:
            print("在 setting.json 中未配置串口，跳过启动串口服务。")
            return True

        cmd = ["autotest-server"]
        print("正在启动串口服务...")

        is_windows = (os.name == 'nt')
        creation_flags = subprocess.CREATE_NO_WINDOW if is_windows else 0

        # Define log file path and open it
        report_dir = get_report_dir()
        serial_server_log_path = os.path.join(report_dir, "serial_server.log")
        serial_server_log_file = open(serial_server_log_path, "w", encoding="utf-8", buffering=1) # Line-buffered

        serial_server_process = subprocess.Popen(
            cmd,
            stdout=serial_server_log_file,
            stderr=serial_server_log_file,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=creation_flags,
            bufsize=1
        )
        time.sleep(2) # 等待服务启动
        if serial_server_process.poll() is not None:
            print("错误: 串口服务进程启动失败，请检查环境。")
            serial_server_log_file.close()
            serial_server_log_file = None
            return False
        print(f"串口服务已启动 (PID: {serial_server_process.pid})。输出将重定向到 {serial_server_log_path}")
        return True

    except FileNotFoundError:
         print("错误: 'autotest-server' 命令未找到。请确保依赖已正确安装且在系统PATH中。")
         if serial_server_log_file:
             serial_server_log_file.close()
             serial_server_log_file = None
         return False
    except Exception as e:
        print(f"启动串口服务失败: {e}")
        traceback.print_exc()
        if serial_server_log_file:
            serial_server_log_file.close()
            serial_server_log_file = None
        return False

def stop_serial_server():
    """ 停止串口服务进程 """
    global serial_server_process, serial_server_log_file
    if serial_server_process and serial_server_process.poll() is None:
        print(f"正在停止串口服务 (PID: {serial_server_process.pid})...")
        try:
            subprocess.run(
                f"taskkill /F /T /PID {serial_server_process.pid}",
                check=True,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            serial_server_process.wait(timeout=5)
            print("串口服务已停止。")
        except FileNotFoundError:
            # 如果 taskkill 不可用，则退回到 terminate
            serial_server_process.terminate()
            print("尝试使用 terminate() 停止服务。")
        except (subprocess.CalledProcessError, ProcessLookupError, PermissionError) as e:
            print(f"停止串口服务时出错: {e}，尝试强制终止。")
            serial_server_process.kill() # 作为最后手段
        except Exception as e:
            print(f"停止串口服务时发生未知错误: {e}")
        finally:
            if serial_server_log_file:
                serial_server_log_file.close()
                serial_server_log_file = None
            serial_server_process = None

def run(cases):
    """
    运行所有测试用例并生成报告.
    """
    report_dir = get_report_dir()
    log_base_dir = os.path.join(report_dir, 'log')

    # 清理旧的报告和日志
    if os.path.isdir(report_dir):
        shutil.rmtree(report_dir)
    os.makedirs(log_base_dir, exist_ok=True)

    # 启动串口服务
    if not start_serial_server():
        print("串口服务启动失败，测试终止。")
        return

    try:
        results_data = []
        start_time = time.time()
        
        # 假设只有一个设备用于演示
        # 在实际多设备场景中, 你需要修改此处的设备列表逻辑
        devices = ["default_device"]

        for case in cases:
            case_results = {'script': case, 'tests': {}}
            
            tasks = run_on_devices(case, devices, log_base_dir)

            for task in tasks:
                status = task['process'].wait()
                report_info = run_one_report(task['case'], task['dev'], log_base_dir)
                # 确保status总是存在
                report_info['status'] = status if status is not None else -1
                case_results['tests'][task['dev']] = report_info

            results_data.append(case_results)

        run_summary(results_data, start_time)

    except Exception:
        traceback.print_exc()
    finally:
        stop_serial_server()

def run_on_devices(case, devices, log_base_dir):
    """
    在指定设备上运行单个测试用例.
    """
    case_name = os.path.splitext(case)[0]
    case_path = os.path.join(os.getcwd(), "case", case, f"{case_name}.py")
    tasks = []
    for dev in devices:
        log_dir = get_log_dir(case, dev, log_base_dir)
        print(f"执行脚本 '{case}' 在设备 '{dev}' 上, 日志路径: {log_dir}")
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.join(os.getcwd(), "case")
        env['PROJECT_ROOT'] = os.getcwd()
        cmd = ["airtest", "run", case_path, "--log", log_dir, "--recording"]
        try:
            # 使用 shell=True (Windows) or False (Linux/MacOS)
            is_windows = os.name == 'nt'
            tasks.append({
                'process': subprocess.Popen(cmd,env=env,cwd=os.getcwd(), shell=is_windows),
                'dev': dev,
                'case': case
            })
        except Exception:
            traceback.print_exc()
    return tasks

def run_one_report(case, dev, log_base_dir):
    """
    为单次运行生成Airtest报告.
    """
    log_dir = get_log_dir(case, dev, log_base_dir)
    log_txt = os.path.join(log_dir, 'log.txt')
    case_name = os.path.splitext(case)[0]
    case_path = os.path.join(os.getcwd(), "case", case, f"{case_name}.py")
    try:
        if os.path.isfile(log_txt):
            report_path = os.path.join(log_dir, 'log.html')
            static_source_path = os.path.join(os.getcwd(), "source")
            cmd = [
                "airtest", "report", case_path,
                "--log_root", log_dir,
                "--outfile", report_path,
                "--lang", "zh",
                "--plugin", "tp_autotest.report"
            ]
            is_windows = os.name == 'nt'
            subprocess.call(cmd, shell=is_windows, cwd=os.getcwd())
            
            relative_path = os.path.join("log", case, dev, 'log.html').replace('\\', '/')
            return {'status': 0, 'path': relative_path}
        else:
            print(f"报告生成失败: 未找到log.txt in {log_dir}")
    except Exception:
        traceback.print_exc()
    return {'status': -1, 'path': ''}

def run_summary(data, start_time):
    """
    汇总所有结果并生成最终的聚合报告.
    """
    static_src = os.path.join(os.getcwd(), "source", "static")
    static_dst = os.path.join(os.getcwd(), "result","static")
    if os.path.isdir(static_src):
        if os.path.isdir(static_dst):
            shutil.rmtree(static_dst, ignore_errors=True)
        shutil.copytree(static_src, static_dst)
    else:
        print("警告: 未找到 source/log_static 目录，汇总报告可能缺少静态资源。")
    try:
        all_statuses = []
        for dt in data:
            dt['description'] = get_script_description(dt['script'])
            for test in dt['tests'].values():
                all_statuses.append(test.get('status', -1))

        summary = {
            'time': f"{(time.time() - start_time):.3f}",
            'success': all_statuses.count(0),
            'count': len(all_statuses),
            'start_all': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time)),
            "result": data
        }

        if os.path.exists("setting.json"):
            with open("setting.json", "r", encoding="utf-8") as f:
                summary.update(json.load(f))

        template_dir = os.path.join(os.getcwd(), "source")
        env = Environment(loader=FileSystemLoader(template_dir), trim_blocks=True)
        template = env.get_template('template.html')
        html = template.render(data=summary)

        report_path = os.path.join(get_report_dir(), "result.html")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        # 使用file URI scheme确保跨平台兼容性
        webbrowser.open('file://' + os.path.realpath(report_path))

    except Exception:
        traceback.print_exc()

def get_log_dir(case, device, log_base_dir):
    """
    构建并创建单个测试运行的日志目录.
    """
    # 清理设备名中的非法字符
    safe_device_name = device.replace(":", "_").replace(".", "_")
    log_dir = os.path.join(log_base_dir, case, safe_device_name)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir

def get_report_dir():
    """
    获取报告的根目录.
    """
    return os.path.join(os.getcwd(), "result")

def get_cases():
    """ 从 'case' 文件夹获取所有测试用例的名称列表。 """
    case_dir = os.path.join(os.getcwd(), "case")
    if not os.path.isdir(case_dir):
        os.makedirs(case_dir)
        return []

    # 返回所有子目录的名称，并排序
    return sorted([
        name for name in os.listdir(case_dir)
        if os.path.isdir(os.path.join(case_dir, name)) and name != 'utils' and not name.startswith(('.', '_'))
    ])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="运行 Airtest 测试用例并生成报告。")
    parser.add_argument(
        '--cases', 
        nargs='+', 
        help='指定要运行的一个或多个测试用例的名称 (例如: case1.air case2.air)。'
    )
    args = parser.parse_args()
    
    if args.cases:
        # 如果通过命令行指定了用例，则使用指定的用例
        cases_to_run = args.cases
        print(f"将要运行指定的测试用例: {cases_to_run}")
    else:
        # 否则，获取 'case' 文件夹下的所有用例
        cases_to_run = get_cases()
        print("未指定测试用例，将运行 'case' 目录下的所有用例。")

    if cases_to_run:
        run(cases_to_run)
    else:
        print("未找到任何测试用例，程序退出。")