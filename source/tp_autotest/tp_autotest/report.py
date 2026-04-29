# -*- coding: utf-8 -*-
import os
import io
from urllib.parse import unquote
import airtest.report.report as report
import json
import jinja2
import shutil
from airtest.core.settings import Settings as ST
from airtest.report.report import nl2br, timefmt
LOGDIR = "log"

old_trans_screen = report.LogToHtml._translate_screen
old_trans_desc = report.LogToHtml._translate_desc
old_trans_code = report.LogToHtml._translate_code
old_trans_info = report.LogToHtml._translate_info
old_render = report.LogToHtml._render

screen_func = [
    "find_element_by_xpath", "find_element_by_id", "find_element_by_name", 
    "find_element_by_css_selector", "find_element_by_class_name", "find_any_element", "find_element_by_text",
    "back", "forward", "switch_to_new_tab", "switch_to_previous_tab", "get", "scroll", "snapshot", "full_snapshot",
    # second_screen functions
    "click", "double_click", "send_keys", "select_item", "text", "is_on",
    # assert functions
    "assert_screen", "assert_custom", "assert_exist", "assert_template", "assert_text", "assert_two_picture",
    # ocr functions
    "find_element_by_ocr", "find_elements_by_ocr", "ocr_touch", "compare_picture",
    ## Model Additional Functions
    "web_login", "web_page", "web_skip_qs", "web_backup", "web_upgrade", "web_restore", "web_factory_restore", "web_switch_ap", "web_switch_router",
]

second_screen_func = ["click", "double_click", "is_on","send_keys", "select_item"]
other_func = [
    "airtest_touch",
    # serial_utils functions
    "serial_open", "serial_close", "serial_login", "serial_send", "serial_get", "serial_find","serial_wait_pattern",
    # network_utils functions
    "wifi_connect", "wifi_disconnect", "get_ip", "ping", "check_port",

]

def new_trans_screen(self, step, code):
    trans = old_trans_screen(self, step, code)
    if "name" in step['data'] and step['data']["name"] in screen_func:
        screen = {
            "src": None,
            "rect": [],
            "pos": [],
            "vector": [],
            "confidence": None,
        }

        src = ""
        if step["data"]["name"] in second_screen_func and 'ret' in step["data"]:
            res = step["data"]['ret']
            if isinstance(res, dict) and "screen" in res:
                src = res["screen"]
                if "pos" in res:
                    screen["pos"] = res["pos"]

        if not src:
            for item in step["__children__"]:
                if item["data"]["name"] in ["_gen_screen_log", "try_log_screen"] and 'ret' in item["data"]:
                    res = item["data"]['ret']
                    if isinstance(res, dict) and "screen" in res:
                        src = res["screen"]
                        if "pos" in res:
                            screen["pos"] = res["pos"]
                        break

        if self.export_dir and src:
            src = os.path.join(LOGDIR, src)
        screen["src"] = src

        # 补充扩展的截图
        extra_screens = []
        main_screen_filename = os.path.basename(screen.get("src") or "")

        for item in step["__children__"]:
            if item["data"]["name"] in ["_gen_screen_log", "try_log_screen", "save_screen"] and 'ret' in item["data"]:
                res = item["data"]['ret']
                if isinstance(res, dict) and "screen" in res:
                    extra_screen_filename = os.path.basename(res["screen"])
                    is_main_screen = extra_screen_filename and extra_screen_filename == main_screen_filename
                    is_already_added = any(os.path.basename(s['src']) == extra_screen_filename for s in extra_screens)

                    if not is_main_screen and not is_already_added:
                        extra_src = os.path.join(LOGDIR, res["screen"]) if self.export_dir else res["screen"]
                        extra_screens.append({
                            "src": extra_src,
                            "pos": res.get("pos", [])
                        })
        if extra_screens: 
            screen['extra_screens'] = extra_screens
        return screen

    elif "name" in step['data'] and step["data"]["name"] in ["airtest_touch"]:
        # 将图像匹配得到的pos修正为最终pos
        display_pos = None
        if self.is_pos(step["data"].get("ret")):
            display_pos = step["data"]["ret"]
        elif self.is_pos(step["data"]["call_args"].get("v")):
            display_pos = step["data"]["call_args"]["v"]
        if display_pos:
            trans["pos"] = [display_pos]
        return trans



def new_translate_desc(self, step, code):
    trans = old_trans_desc(self, step, code)
    if "name" in step['data'] and code:
        name = step["data"]["name"]
        args = {}
        url = ""
        for item in code["args"]:
            if (name=='get'):
                url = unquote(item['value'])
                item['value'] = " %s " % url
            args[item['key']] = item['value']

        if (step['data']["name"] in screen_func or step["data"]["name"] in other_func):
            desc = {
                "find_element_by_xpath": lambda: u"Find element by xpath: %s" % args.get("xpath"),
                "find_element_by_id": lambda: u"Find element by id: %s" % args.get("id"),
                "find_element_by_name": lambda: u"Find element by name: %s" % args.get("name"),
                "assert_screen": "Assert a picture with screen snapshot",
                "assert_custom": "Assert custom",
                "assert_exist": u"Assert element exists.",
                "assert_serial_log": lambda: f"Assert serial log: \"{args.get('pattern')}\"",
                "click": u"Click the element that been found.",
                "send_keys": u"Send some text and keyboard event to the element that been found.",
                "get": lambda: u"Get the web address: %s" % (url),
                "switch_to_last_window": u"Switch to the last tab.",
                "switch_to_latest_window": u"Switch to the new tab.",
                "back": u"Back to the last page.",
                "forward": u"Forward to the next page.",
                "snapshot": lambda: (u"Screenshot description: %s" % args.get("msg")) if args.get("msg") else u"Snapshot current page",
                "full_snapshot": lambda: f"full snapshot: {args.get('msg')}" if args.get('msg') else "full snapshot"

            }

            desc_zh = {
                # Selenium Web 页面元素操作
                "find_element_by_xpath": lambda: f"寻找: \"{args.get('xpath')}\"",
                "find_element_by_id": lambda: f"寻找: \"{args.get('id')}\"",
                "find_element_by_name": lambda: f"寻找: \"{args.get('name')}\"",
                "find_element_by_css_selector": lambda: f"寻找: \"{args.get('css_selector')}\"",
                "find_element_by_class_name": lambda: f"寻找: \"{args.get('name')}\"",
                "find_element_by_text": lambda: f"寻找: \"{args.get('text')}\"",
                "find_any_element": "寻找",

                # 子步骤与输入
                "click": "点击页面元素",
                "double_click": "双击页面元素",
                "send_keys": lambda: f"输入内容: \"{args.get('value', '')}\"",
                "select_item": lambda: f"下拉框选择: \"{args.get('text', '')}\"",
                "text": lambda: f"获取该位置文本",
                "is_on": "获取开关的值",

                # 浏览器控制
                "get": lambda: f"访问: {url}",
                "switch_to_previous_tab": "切换到上一个标签页",
                "switch_to_new_tab": "切换到最新标签页",
                "back": "后退到上一个页面",
                "forward": "前进到下一个页面",
                "scroll": "滚动当前页面",
                
                # Airtest & 截图操作
                "airtest_touch": "点击图片",
                "snapshot": lambda: f"截取当前页面: {args.get('msg')}" if args.get('msg') else "截取当前页面",
                "full_snapshot": lambda: f"截取页面长图: {args.get('msg')}" if args.get('msg') else "截取页面长图",

                # 断言操作
                "assert_exist": lambda: f"断言元素存在: \"{args.get('param')}\" (通过 {args.get('operation')})",
                "assert_template": lambda: f"断言图片存在: {args.get('msg')}" if args.get('msg') else "断言图片存在于屏幕",
                "assert_text": lambda: f"断言文字存在: \"{args.get('text')}\"",
                "assert_screen": lambda: f"断言相似度: {args.get('msg')}" if args.get('msg') else "对比当前屏幕与图片",
                "assert_two_picture": lambda: f"断言相似度: {args.get('msg')}" if args.get('msg') else "对比两张指定图片",
                "assert_custom": lambda: f"断言: {args.get('msg')}" if args.get('msg') else "执行自定义断言",

                # OCR 相关操作
                "ocr_touch": lambda: f"点击: \"{args.get('text')}\"",
                "find_element_by_ocr": lambda: f"寻找: \"{args.get('anchor_text')}\"相对元素",
                "find_elements_by_ocr": lambda: f"寻找: \"{args.get('anchor_text')}\"",
                "compare_picture": lambda: f"对比图片: {args.get('msg')}" if args.get('msg') else "对比图片相似度",


                # 串口工具函数
                "serial_open": lambda: f"打开串口{args.get('port')}" if args.get('port') else "打开串口",
                "serial_close": lambda: f"关闭串口{args.get('port')}" if args.get('port') else "关闭串口",
                "serial_login": lambda: f"登录串口{args.get('port')}" if args.get('port') else "登录串口",
                "serial_send": lambda: f"串口{args.get('port')}发送: {args.get('command')}" if args.get('port') else f"串口发送: {args.get('command')}",
                "serial_get": lambda: f"串口{args.get('port')}" if args.get('port') else "串口" + f"获取日志 (最近 {args.get('lines')} 行)" if args.get('lines') else (f"获取串口日志 (最近 {args.get('duration')} 秒)" if args.get('duration') else "获取全部串口日志"),
                "serial_find": lambda: f"串口{args.get('port')}" if args.get('port') else "串口" + f"日志中搜索: \"{args.get('pattern')}\"",
                "serial_wait_pattern": lambda: f"串口{args.get('port')}" if args.get('port') else "串口" + f"等待日志出现: \"{args.get('pattern')}\"",

                # 网络工具函数
                "wifi_connect": lambda: f"连接WiFi: {args.get('ssid')}",
                "wifi_disconnect": "断开WiFi连接",
                "get_ip": lambda: f"获取 {args.get('interface_type', '默认')} 网卡IP",
                "ping": lambda: f"Ping IP地址: {args.get('ip_address')}",
                "check_port": lambda: f"检查端口状态: {args.get('host')}:{args.get('port')}",


                # 机型附件的函数
                "web_login": lambda: f"登录网页: {args.get('url')}",
                "web_skip_qs": lambda: f"跳过快速配置",
                "web_page": lambda: "回到首页" if args.get('text')=="" or args.get('text')=="/" else f"进入子页面: {args.get('text')}",
                "web_backup": lambda: f"导出配置: {args.get('text')}",
                "web_upgrade": lambda: f"升级软件: {args.get('text')}",
                "web_restore": lambda: f"导入备份配置: {args.get('text')}",
                "web_factory_restore": lambda: f"恢复出厂设置",
                "web_switch_ap": lambda: f"切换到AP模式",
                "web_switch_router": lambda: f"切换到Router模式",
                
            }
            predefined_desc = desc_zh.get(name)
            if predefined_desc:
                return predefined_desc() if callable(predefined_desc) else predefined_desc
            elif 'msg' in args and args['msg']:
                return str(args['msg'])
            else:
                return trans
        else:
            if args.get('msg'):
                return str(args.get('msg'))

    return trans

def new_translate_code(self, step):
    """
    处理代码显示逻辑。
    增加了一个过滤器，当函数是 assert_custom 或 assert_serial_log 时，
    会主动移除名为 'logs' 的参数，避免其在报告中重复显示。
    """
    # 先调用原始的翻译函数获取所有参数
    trans = old_trans_code(self, step)

    if trans:
        # 准备一个要过滤掉的参数名列表
        params_to_filter = ["self"]

        # func_name = step["data"]["name"]
        # if func_name in ["assert_custom", "assert_serial_log"]:
        params_to_filter.append("log_msg")

        trans["args"] = [arg for arg in trans["args"] if arg.get("key") not in params_to_filter]
        
    return trans

def new_translate_info(self, step):
    trace_msg, log_msg = old_trans_info(self, step)
    if "log" in step["data"]:
        log_msg = step["data"]["log"]

    if isinstance(log_msg, dict):
        try:
            # 尝试将字典格式化为JSON字符串
            pretty_json = json.dumps(log_msg, indent=4, ensure_ascii=False)
            log_msg = f"{pretty_json}"
        except Exception:
            pass

    return trace_msg, log_msg

def _ensure_trailing_slash(path):
    if not path:
        return path
    return path if path.endswith("/") else path + "/"


def _normalize_path_for_html(path, base_dir=None):
    if not path:
        return ""
    path_str = str(path)
    if path_str.startswith(("http://", "https://")):
        return path_str
    normalized = path_str
    if base_dir and os.path.isabs(path_str):
        try:
            normalized = os.path.relpath(path_str, base_dir)
        except ValueError:
            normalized = path_str
    normalized = normalized.replace("\\", "/")
    return normalized


def _normalize_screen(screen, base_dir):
    if not isinstance(screen, dict):
        return
    if screen.get("src"):
        screen["src"] = _normalize_path_for_html(screen["src"], base_dir)
    if screen.get("extra_screens"):
        for extra in screen["extra_screens"]:
            if isinstance(extra, dict) and extra.get("src"):
                extra["src"] = _normalize_path_for_html(extra["src"], base_dir)


def _refresh_embedded_data(template_vars):
    payload_keys = [
        "steps", "name", "scale", "test_result", "run_end", "run_start",
        "static_root", "lang", "records", "info", "log", "console"
    ]
    payload = {key: template_vars.get(key) for key in payload_keys}
    template_vars["data"] = json.dumps(payload, ensure_ascii=False).replace("<", "＜").replace(">", "＞")

@staticmethod
def new_render(template_name, output_file=None, **template_vars):
    template_path = os.path.join(os.path.dirname(__file__), 'page', 'log_template')
    static_src_path = os.path.join(template_path, 'static')
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path),
        extensions=(),
        autoescape=True,
    )
    env.filters['nl2br'] = nl2br
    env.filters['datetime'] = timefmt

    output_dir = os.path.dirname(os.path.abspath(output_file)) if output_file else os.path.join(os.getcwd(),"result")
    dafault_static_dir = os.path.abspath(os.path.join(ST.PROJECT_ROOT, "result", "static")) if ST.PROJECT_ROOT else os.path.join(os.getcwd(),"result", "static")
    rel_static_root = os.path.relpath(dafault_static_dir, output_dir).replace("\\", "/")
    template_vars["static_root"] = _ensure_trailing_slash(rel_static_root)
    shutil.copytree(static_src_path, dafault_static_dir, dirs_exist_ok=True)

    base_dir = output_dir
    steps = template_vars.get("steps") or []
    for step in steps:
        _normalize_screen(step.get("screen"), base_dir)
        code = step.get("code")
        if code and isinstance(code.get("args"), list):
            for arg in code["args"]:
                if isinstance(arg, dict) and arg.get("image"):
                    arg["image"] = _normalize_path_for_html(arg["image"], base_dir)

    if template_vars.get("records"):
        template_vars["records"] = [
            _normalize_path_for_html(record, base_dir) for record in template_vars["records"]
        ]

    if template_vars.get("log"):
        template_vars["log"] = _normalize_path_for_html(template_vars["log"], base_dir)

    _refresh_embedded_data(template_vars)

    template = env.get_template(template_name)
    html = template.render(**template_vars)

    if output_file:
        with io.open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)
        print(output_file)

    return html

report.LogToHtml._render = new_render
report.LogToHtml._translate_screen = new_trans_screen
report.LogToHtml._translate_desc = new_translate_desc
report.LogToHtml._translate_code = new_translate_code
report.LogToHtml._translate_info = new_translate_info
