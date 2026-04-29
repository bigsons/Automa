# -*- coding: utf-8 -*-

from selenium.webdriver import Chrome, ActionChains, Firefox, Remote
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from airtest.core.settings import Settings as ST
from airtest.core.helper import logwrap
from airtest import aircv
from airtest.core.cv import Template
from tp_autotest.utils.airtest_api import loop_find, try_log_screen, set_step_log, set_step_traceback
from airtest.aircv import get_resolution
from pynput.mouse import Controller, Button
from airtest.core.error import TargetNotFoundError
from airtest.aircv.cal_confidence import cal_rgb_confidence
from .utils.serial_utils import SerialManager
from .utils.network_utils import WifiManager, get_ip_address, ping
from .utils.ocr_utils import OcrHelper

import selenium
import os
import time
import sys
import numpy as np
import json
import cv2
import subprocess

from airtest import aircv
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from paddleocr import PaddleOCR

class WebChrome(Chrome):

    def __init__(self, executable_path="chromedriver", port=0,
                 options=None, service=None, keep_alive=None, service_args=None,
                 desired_capabilities=None, service_log_path=None,
                 chrome_options=None):
        """初始化Chrome Selenium驱动。

        Example:
            在脚本开始时创建 WebChrome() 实例。
        """
        if "darwin" in sys.platform:
            os.environ['PATH'] += ":/Applications/AirtestIDE.app/Contents/Resources/selenium_plugin"

        self.download_directory = None
        if selenium.__version__ >= "4.10.0":
            if not options:
                options = Options()
            options.add_argument("--window-size=929,1036")
            options.binary_location=os.path.join(os.environ.get("ProgramFiles", "C:/Program Files"),"Automa/chrome/chrome.exe")
            # options.add_argument("--force-device-scale-factor=0.9") # Bug: 添加缩放之后点击功能失效

            self.download_directory = os.path.join(ST.LOG_DIR or ".", "downloads")
            if not os.path.exists(self.download_directory):
                os.makedirs(self.download_directory)
            prefs = {
                "download.default_directory": self.download_directory,
                "download.prompt_for_download": False, # 禁止下载前弹出保存框
            }
            options.add_experimental_option("prefs", prefs)
            if os.name == 'nt':
                if service is None:
                    service = Service()
                service.creationflags = getattr(service, "creationflags", 0) | subprocess.CREATE_NO_WINDOW
            if port != 0 or service_args != None or desired_capabilities != None or chrome_options != None or service_log_path != None:
                print("Warning: 'Valid parameters = options, service, keep_alive'.")
            super(WebChrome, self).__init__(options=options, service=service,
                                            keep_alive=keep_alive)
        else:
            raise AssertionError("Unsupported Selenium Version")

        self.father_number = {0: 0}
        self.ocr_helper = OcrHelper(self)
        self.action_chains = ActionChains(self)
        self.number = 0
        self.mouse = Controller()
        self.operation_to_func = {"elementsD": self.find_any_element, "xpath": self.find_element_by_xpath,
                                  "id": self.find_element_by_id,
                                  "name": self.find_element_by_name, "css": self.find_element_by_css_selector}
        
        # 补充功能
        self.settings = self._load_settings()
        self.serial_manager = None
        self.wifi_manager = None

        try:
            self.serial_manager = SerialManager()
            if self.get_setting("default_serial"):
                self.serial_open(self.get_setting("default_serial")) 
        except Exception as e:
            self.serial_manager = None
            print(f"初始化串口功能失败: {e}")

        if self.settings.get("wireless_adapter"):
            try:
                self.wifi_manager = WifiManager(self.settings["wireless_adapter"])
            except Exception as e:
                print(f"初始化WifiManager失败: {e}")

    def _load_settings(self):
        """从项目根目录加载 setting.json 配置文件。"""
        try:
            with open(ST.PROJECT_ROOT + "/setting.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            print("未找到 setting.json 配置文件。")
            return {}

    def get_setting(self, key=None, default=None):
        """获取setting.json中的配置项。

        Args:
            key (str, optional): 要获取的配置项的键。如果为None，则返回整个配置字典。
            default (any, optional): 当键不存在时返回的默认值。

        Returns:
            any: 配置值或整个配置字典。

        Example:
            ``self.get_setting("default_serial")``
        """
        if key:
            return self.settings.get(key, default)
        return self.settings

    def loop_find_element(self, func, text, by=By.ID, timeout=10, interval=0.5):
        """在指定超时时间内，循环查找一个Web元素。如果找不到会抛出异常。

        这是一个内部辅助函数，通常被 find_element_by_xpath 等函数调用。

        Args:
            func (function): 用来查找元素的函数，如 super().find_element。
            text (str): 查找时使用的定位器字符串 (如xpath路径)。
            by (str): 定位策略 (如 By.XPATH)。
            timeout (int): 超时时间（秒）。
            interval (float): 循环查找的间隔时间（秒）。

        Returns:
            WebElement: 找到的 WebElement 对象。

        Raises:
            NoSuchElementException: 如果在超时后仍未找到元素。
        """
        start_time = time.time()
        while True:
            try:
                element = func(by, text)
            except NoSuchElementException:
                # 超时则raise，未超时则进行下次循环:
                if (time.time() - start_time) > timeout:
                    # try_log_screen(screen)
                    raise NoSuchElementException(
                        'Element %s not found in screen' % text)
                else:
                    time.sleep(interval)
            else:
                return element

    def loop_find_element_noExc(self, func, text, by=By.ID, timeout=3, interval=0.5):
        """在指定超时时间内，循环查找一个Web元素。如果找不到不抛出异常，而是返回None。

        这是一个内部辅助函数，主要被 find_any_element 调用。

        Args:
            func (function): 用来查找元素的函数。
            text (str): 查找时使用的定位器字符串。
            by (str): 定位策略。
            timeout (int): 超时时间（秒）。
            interval (float): 循环查找的间隔时间（秒）。

        Returns:
            WebElement or None: 找到的 WebElement 对象或 None。
        """
        start_time = time.time()
        while True:
            try:
                element = func(by, text)
            except NoSuchElementException:
                if (time.time() - start_time) > timeout:
                    # try_log_screen(screen)
                    return None
                else:
                    time.sleep(interval)
            else:
                print('element found')
                return element

    def find_any_element(self, elementsD):
        """使用一个包含多种定位策略的字典来查找Web元素，只要其中一种策略成功找到，就立即返回。

        Args:
            elementsD (dict): 一个字典，键为定位策略 (ID, XPATH, CSS等)，值为定位器字符串。

        Returns:
            Element: 包装后的 Element 对象。
        
        Raises:
            NoSuchElementException: 如果所有策略都失败。

        Example:
            ``self.find_any_element({"ID": "user", "XPATH": "//input[@name='username']"})``
        """
        web_element = None
        for key in elementsD:
            value = elementsD[key]
            print(value)
            if key.upper() == 'ID':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.ID)
            elif key.upper() == 'XPATH':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.XPATH)
            elif key.upper() == 'CSS':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.CSS_SELECTOR)
            elif key.upper() == 'NAME':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.NAME)
            elif key.upper() == 'LINKTEXT':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.LINK_TEXT)
            elif key.upper() == 'CLASSNAME':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.CLASS_NAME)
            elif key.upper() == 'PARTIALLINKTEXT':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.PARTIAL_LINK_TEXT)
            elif key.upper() == 'TAGNAME':
                web_element = self.loop_find_element_noExc(super().find_element, value, by=By.TAG_NAME)
            # check by position/ picture / visual testing
            if web_element is not None:
                break
        if web_element is not None:
            log_res = self._gen_screen_without_log(web_element)
            return Element(web_element, log_res)
        raise NoSuchElementException('Element not found in screen')

    def find_elements_by_class_name(self, name):
        """查找所有具有指定 class name 的元素。

        Args:
            name (str): 元素的 class name。

        Returns:
            list[WebElement]: 一个包含 WebElement 对象的列表。

        Example:
            ``elements = driver.find_elements_by_class_name('foo')``
        """
        return self.find_elements(by=By.CLASS_NAME, value=name)

    def find_elements_by_xpath(self, xpath):
        """查找所有匹配指定 xpath 的元素。

        Args:
            xpath (str): xpath 定位器。

        Returns:
            list[WebElement]: 一个包含 WebElement 对象的列表。

        Example:
            ``elements = driver.find_elements_by_xpath("//div")``
        """
        return self.find_elements(by=By.XPATH, value=xpath)

    def find_elements_by_text(self, text):
        """查找所有匹配指定 text 的元素。

        Args:
            text (str): text 文本。

        Returns:
            list[WebElement]: 一个包含 WebElement 对象的列表。

        Example:
            ``elements = driver.find_elements_by_text("//div")``
        """
        
        target_xpath = f"//*[(normalize-space()='{text}' and not(./ *[normalize-space()='{text}'])) or text()[normalize-space()='{text}'] ]"
        elements = super(WebChrome, self).find_elements(by=By.XPATH, value=target_xpath)
        return [element for element in elements if element.is_displayed()]

    def find_elements_by_ocr(self, text, offset):
        """使用OCR查找所有匹配指定文本的元素。

        Args:
            anchor_text (str): 要查找的文字。
            timeout (int): 查找超时时间。

        Returns:
            list: 包含所有匹配项坐标和信息的元素列表。
            
        Example:
            ``self.find_elements_by_ocr("选项")``
        """
        return self.ocr_helper.ocr_find_elements(text,offset)

    def find_element_by_ocr(self, anchor_text, steps=None, offset=None, timeout=10):
        """使用OCR先定位一个锚点文字，然后根据相对步骤查找目标元素。

        Args:
            anchor_text (str): 锚点文字。
            steps (list[str]): 描述相对位置的步骤列表，如 ["right", "down"]。
            timeout (int): 查找超时时间。

        Returns:
            WebElement: 找到的元素。
            
        Example:
            ``self.find_element_by_ocr("用户名", steps=["right"])``
        """
        return self.ocr_helper.ocr_find_element_by_step(anchor_text, steps,  offset, timeout)

    def find_element_by_xpath(self, xpath, timeout=10):
        """通过 xpath 查找单个Web元素，并自动截图记录。

        Args:
            xpath (str): 元素的 xpath 路径。

        Returns:
            Element: 包装后的 Element 对象。

        Example:
            ``element = self.find_element_by_xpath("//div[@id='main']")``
        """
        web_element = self.loop_find_element(super(WebChrome, self).find_element, xpath, by=By.XPATH, timeout=timeout)
        # web_element = super(WebChrome, self).find_element_by_xpath(xpath)
        log_res = self._gen_screen_without_log(web_element)
        return Element(web_element, log_res)

    def find_element_by_text(self, text, timeout=10):
        """通过文本查找一个可见元素, 此方法使用Selenium实现

        Args:
            text (str): 元素的文本内容。
            timeout (int): 超时时间（秒）。

        Returns:
            Element: 包装后的 Element 对象。

        Example:
            ``element = self.find_element_by_text("LOGIN")``
        """
        # target_xpath = f"//*[text()[normalize-space()='{text}']]" # 匹配部分子元素
        # target_xpath = f"//*[normalize-space(string(.))='{text}']" # 匹配整个文本，等价于//*[(normalize-space()='{text}']
        # 究极版本，同时处理整串匹配和子元素匹配
        target_xpath = f"//*[(normalize-space()='{text}' and not(./ *[normalize-space()='{text}'])) or text()[normalize-space()='{text}'] ]"

        def find_visible_element(by, value):
            """包装函数：找到元素后检查是否可见，不可见则抛异常触发重试"""
            elements = super(WebChrome, self).find_elements(by, value)
            if not elements:
                raise NoSuchElementException(f"No element found with text: {text}")
            for elem in elements:
                if elem and elem.is_displayed():
                    return elem
            raise NoSuchElementException(f"No element found with text: {text}")

        web_element = self.loop_find_element(find_visible_element, target_xpath, by=By.XPATH, timeout=timeout)
        log_res = self._gen_screen_without_log(web_element)
        return Element(web_element, log_res)

    def find_element_by_id(self, id, timeout=10):
        """通过元素的 id 属性查找单个Web元素，并自动截图记录。

        Args:
            id (str): 元素的 id 值。

        Returns:
            Element: 包装后的 Element 对象。

        Example:
            ``element = self.find_element_by_id("username")``
        """
        web_element = self.loop_find_element(super(WebChrome, self).find_element, id, by=By.ID, timeout=timeout)
        log_res = self._gen_screen_without_log(web_element)
        return Element(web_element, log_res)

    def find_element_by_css_selector(self, css_selector, timeout=10):
        """通过 CSS 选择器查找单个Web元素，并自动截图记录。

        Args:
            css_selector (str): 元素的 CSS 选择器。

        Returns:
            Element: 包装后的 Element 对象。

        Example:
            ``element = self.find_element_by_css_selector("div#main > p")``
        """
        web_element = self.loop_find_element(super(WebChrome, self).find_element, css_selector, by=By.CSS_SELECTOR, timeout=timeout)
        log_res = self._gen_screen_without_log(web_element)
        return Element(web_element, log_res)

    def find_element_by_class_name(self, name, timeout=10):
        """通过 class name 查找单个Web元素，并自动截图记录。

        Args:
            name (str): 元素的 class name。

        Returns:
            Element: 包装后的 Element 对象。

        Example:
            ``element = self.find_element_by_class_name("form-control")``
        """
        web_element = self.loop_find_element(super(WebChrome, self).find_element, name, by=By.CLASS_NAME, timeout=timeout)
        log_res = self._gen_screen_without_log(web_element)
        return Element(web_element, log_res)

    def find_element_by_name(self, name, timeout=10):
        """通过元素的 name 属性查找单个Web元素，并自动截图记录。

        Args:
            name (str): 元素的 name 属性值。

        Returns:
            Element: 包装后的 Element 对象。

        Example:
            ``element = self.find_element_by_name("username")``
        """
        web_element = self.loop_find_element(super(WebChrome, self).find_element, name, by=By.NAME, timeout=timeout)
        log_res = self._gen_screen_without_log(web_element)
        return Element(web_element, log_res)

    def find(self, v, steps=None, offset=(0,0), timeout=10):
        """
        统一的查找函数，可以根据输入参数的类型自动选择最合适的查找策略。

        Args:
            v (Template or str or dict): 查找目标。
                - 当 v 是 Template 对象或者图片路径时: 进行图像匹配。
                - 当 v 是 str 时: 进行文本查找。
                - 当 v 是 dict 时: 使用 find_any_element 进行混合定位器查找。
            steps (list[str], optional): 当 v 是文本时，用于OCR相对定位的步骤。默认为 None。
            offset (tuple, optional): 应用于最终找到的位置的(x, y)偏移量。默认为(0, 0)。
            timeout (int, optional): 查找超时时间（秒）。默认为 10。

        Returns:
            Element or OcrElement: 找到的元素对象。

        Raises:
            TargetNotFoundError: 如果通过任何方式都找不到目标。
        """

        if isinstance(v, str):
            lower_v = v.lower()
            if lower_v.endswith(('.png', '.jpg', '.jpeg')):
                if os.path.isfile(v):
                    v = Template(v) 
        try:
            if isinstance(v, Template):
                pos = loop_find(v, driver=self, timeout=timeout)
                final_pos = (pos[0] + offset[0], pos[1] + offset[1])
                element_data = {'center': final_pos, 'text': f"Image({v.filename})"}
                log_res = self._gen_screen_without_log()
                log_res["pos"] = [final_pos]
                return OcrElement(self, element_data, log_res)

            elif isinstance(v, str):
                if steps or offset != (0, 0):
                    return self.ocr_helper.ocr_find_element_by_step(v, steps=steps, offset=offset, timeout=timeout)
                elif v.strip().startswith("//"):
                    return self.find_element_by_xpath(v,timeout)
                else:
                    try:
                        return self.find_element_by_text(v)
                    except NoSuchElementException:
                        print(f"Selenium 查找失败, 尝试使用 OCR 查找 '{v}'...")
                        return self.ocr_helper.ocr_find_element_by_step(v, timeout=timeout)

            # 3. 如果 v 是字典，使用 find_any_element
            elif isinstance(v, dict):
                return self.find_any_element(v)

            else:
                raise TypeError("find 函数的 v 参数必须是 Template图片 或文本str  或 dict 类型。")

        except (TargetNotFoundError, NoSuchElementException) as e:
            print(f"Find 函数执行失败: {e}")
            raise TargetNotFoundError(f"在 {timeout} 秒内未能通过任何方式找到'{v}'相关的目标元素")

    def finds(self, text, offset=None, timeout=10):
        """查找多个符合条件的元素，优先使用 Selenium，其次使用 OCR。

        Args:
            text (str): 元素的 text 值。

        Returns:
            Element[] or OcrElement[]: 找到的元素对象列表。
        """
        
        if not isinstance(text, str):
            raise TypeError("finds 函数当前仅支持文本 str 类型。")

        start_time = time.time()
        interval = 0.5

        printed_fallback = False

        while True:
            results = []
            if text.strip().startswith("//"):
                selenium_elements = self.find_elements(By.XPATH, value=text)
            else:
                selenium_elements = self.find_elements_by_text(text)

            for element in selenium_elements:
                log_res = self._gen_screen_without_log(element)
                results.append(Element(element, log_res))

            if not results and not printed_fallback:
                print(f"Selenium 未找到元素列表, 尝试使用 OCR 查找 '{text}'...")
                printed_fallback = True

            if not results or offset!=None:
                ocr_elements = self.find_elements_by_ocr(text,offset)
                results.clear()
                results.extend(ocr_elements)

            if results:
                return results

            if (time.time() - start_time) > timeout:
                raise TargetNotFoundError(f"在 {timeout} 秒内未能找到任何与 '{text}' 匹配的元素")

            time.sleep(interval)


    @logwrap
    def switch_to_new_tab(self):
        """切换到最新打开的浏览器标签页。

        Example:
            ``self.switch_to_new_tab()``
        """
        _father = self.number
        self.number = len(self.window_handles) - 1
        self.father_number[self.number] = _father
        self.switch_to.window(self.window_handles[self.number])
        self._gen_screen_log()
        time.sleep(0.5)

    @logwrap
    def switch_to_previous_tab(self):
        """切换回上一个标签页（即打开当前标签页的前一个）。

        Example:
            ``self.switch_to_previous_tab()``
        """
        self.number = self.father_number[self.number]
        self.switch_to.window(self.window_handles[self.number])
        self._gen_screen_log()
        time.sleep(0.5)

    @logwrap
    def airtest_touch(self, v):
        """使用Airtest的图像识别或坐标进行点击。

        Args:
            v (Template or tuple): 一个 Template 对象或一个 (x, y) 坐标元组。

        Returns:
            tuple: 最终点击的坐标。
        
        Example:
            ``self.airtest_touch(Template("template.png"))``
            ``self.airtest_touch((100, 200))``
        """
        if isinstance(v, Template):
            _pos = loop_find(v, timeout=ST.FIND_TIMEOUT, driver=self)
            element_data = {'center': _pos, 'text': f"Image({v.filename})"}
            log_res = self._gen_screen_without_log()
            log_res["pos"] = [_pos]
            tmp_ele = OcrElement(self, element_data, log_res)
            tmp_ele.click()
            return _pos
        else:
            screen = self.screenshot()
            try_log_screen(screen)
            _pos = v
            x, y = _pos
            # self.action_chains.move_to_element_with_offset(root_element, x, y)
            # self.action_chains.click()
            pos = self._get_left_up_offset()
            pos = (pos[0] + x, pos[1] + y)
            self._move_to_pos(pos)
            self._click_current_pos()
            time.sleep(1)
            return _pos

    @logwrap
    def assert_template(self, v, msg="测试点"):
        """断言指定的图片存在于当前屏幕上。

        Args:
            v (Template): 要断言的 Template 对象。
            msg (str): 断言失败时的自定义消息。

        Returns:
            tuple: 图片在屏幕上的坐标。

        Raises:
            AssertionError: 如果未找到目标图片。
            AssertionError: 如果传入的v不是Template对象。
        
        Example:
            ``self.assert_template(Template("logo.png"), msg="检查Logo是否存在")``
        """
        if isinstance(v, Template):
            try:
                pos = loop_find(v, timeout=ST.FIND_TIMEOUT, driver=self)
            except TargetNotFoundError:
                raise AssertionError("Target template not found on screen.")
            else:
                return pos
        else:
            raise AssertionError("args is not a template")

    @logwrap
    def assert_exist(self, param, operation, msg="测试点"):
        """断言指定的Web元素存在。

        Args:
            param (str): 元素的定位器字符串。
            operation (str): 定位策略 (如 "id", "xpath")。
            msg (str): 断言失败时的自定义消息。

        Raises:
            AssertionError: 如果操作类型无效或未找到目标元素。
            
        Example:
            ``self.assert_exist("username", operation="id", msg="检查用户名输入框是否存在")``
        """
        try:
            func = self.operation_to_func[operation]
        except Exception:
            raise AssertionError("There was no operation: %s" % operation)
        try:
            func(param)
        except Exception as e:
            raise AssertionError("Target element not find.")

    @logwrap
    def assert_text(self, text, timeout=10, interval=0.5, msg="测试点"):
        """使用OCR断言指定的文本存在于当前屏幕上。

        Args:
            text (str): 要查找的文本。
            timeout (int): 查找的超时时间。
            interval (float): 轮询间隔。
            msg (str): 断言失败时的自定义消息。

        Returns:
            tuple: 文本在屏幕上的坐标。

        Example:
            ``self.assert_text("登录成功", msg="检查登录成功提示")``
        """
        return self.ocr_helper.find_text(text, timeout=timeout, interval=interval)

    @logwrap
    def assert_custom(self, param, log_msg=None, screenshot=None, msg="测试点"):
        """自定义断言，可以根据传入的表达式判断成功或失败，并记录自定义日志。

        Args:
            param (bool): 一个表达式或布尔值，True表示成功，False表示失败。
            log_msg (str or dict): 要记录在报告中的日志信息。
            screenshot (bool or str or dict): 是否截图 (True/False)，或指定图片路径。
            msg (str): 断言步骤的描述。

        Raises:
            AssertionError: 如果param为False。

        Example:
            ``self.assert_custom(1 + 1 == 2, log_msg="数学计算正确", msg="检查加法")``
        """
        if isinstance(screenshot, dict):
            screenshotshot_path = os.path.join(ST.LOG_DIR, screenshot["screen"])
            screen = aircv.imread(screenshotshot_path,)
            try_log_screen(screen,screenshotshot_path)
        elif isinstance(screenshot, str):
            screen = aircv.imread(screenshot)
            try_log_screen(screen,screenshot)
        elif screenshot == True:
            self._gen_screen_log()
        if not (param) :
            raise AssertionError(f"{msg} Custom step execution failed. Log: \n\n{log_msg}")
        else :
            set_step_log(log_msg)

    @logwrap
    def assert_screen(self, old_screen_path, threshold=0.95, msg="测试点"):
        """对比当前屏幕截图与指定的基准图片，断言它们的相似度是否在阈值之上。

        Args:
            old_screen_path (str): 基准图片的路径。
            threshold (float): 相似度阈值 (0到1之间)。
            msg (str): 断言失败时的自定义消息。
        
        Raises:
            IOError: 如果基准图片读取失败。
            ValueError: 如果两张图片尺寸不一致。
            AssertionError: 如果相似度低于阈值。

        Example:
            ``self.assert_screen("c:/path/baseline.png", threshold=0.95, msg="对比首页截图")``
        """
        new_screen = self.screenshot()
        self._gen_screen_log()
        # 2. Read old screenshot
        try:
            old_screen = aircv.imread(old_screen_path)
        except Exception as e:
            raise IOError("Failed to read old screen image at path: %s. Error: %s" % (old_screen_path, e))

        # 3. Compare them using the correct function: aircv.cal_rgb_confidence
        try:
            result = cal_rgb_confidence(old_screen, new_screen)
        except Exception as e:
            print("Could not compare images, likely due to different sizes. Error: %s" % e)
            raise AssertionError("%s Screens could not be compared due to different sizes." % msg)

        # 检查图片尺寸是否一致
        # if old_screen.shape != new_screen.shape:
        #     raise ValueError("Images must have the same dimensions for comparison. "
        #                     "Old: %s, New: %s" % (old_screen.shape, new_screen.shape))
        old_screen, new_screen = self._equalize_image_heights(old_screen, new_screen)
        # 生成并获取对比图的文件名
        self._generate_diff_image(old_screen, new_screen, result)

        if result < threshold:
            raise AssertionError("%s 图片差异过大:%s." % (msg, result))


    @logwrap
    def assert_two_picture(self, old_screen_path, new_screen_path,threshold=0.9, msg="测试点"):
        """对比两张指定的图片，断言它们的相似度是否在阈值之上。

        Args:
            old_screen_path (str): 第一张基准图片的路径。
            new_screen_path (str): 第二张待对比图片的路径。
            threshold (float): 相似度阈值 (0到1之间)。
            msg (str): 断言失败时的自定义消息。
        """
        try:
            old_screen = aircv.imread(old_screen_path)
            new_screen = aircv.imread(new_screen_path)
        except Exception as e:
            raise IOError("Failed to read old screen image at path: %s. Error: %s" % (old_screen_path, e))

        # 3. Compare them using the correct function: aircv.cal_rgb_confidence
        try:
            result = cal_rgb_confidence(old_screen, new_screen)
        except Exception as e:
            print("Could not compare images, likely due to different sizes. Error: %s" % e)
            raise AssertionError("%s Screens could not be compared)." % msg)

        # 检查图片尺寸是否一致
        # if old_screen.shape != new_screen.shape:
        #     raise ValueError("Images must have the same dimensions for comparison. "
        #                     "Old: %s, New: %s" % (old_screen.shape, new_screen.shape))
        # 生成并获取对比图的文件名
        old_screen, new_screen = self._equalize_image_heights(old_screen, new_screen)
        self._generate_diff_image(old_screen, new_screen)

        if result < threshold:
            raise AssertionError("%s 图片差异过大:%s." % (msg, result))

    @logwrap
    def compare_picture(self, old_screen_path, new_screen_path,threshold=0.9, msg="测试点"):
        """对比两张指定的图片，断言它们的相似度是否在阈值之上。

        Args:
            old_screen_path (str): 第一张基准图片的路径。
            new_screen_path (str): 第二张待对比图片的路径。
            threshold (float): 相似度阈值 (0到1之间)。
            msg (str): 自定义名称。
        """
        try:
            old_screen = aircv.imread(old_screen_path)
            new_screen = aircv.imread(new_screen_path)
        except Exception as e:
            raise IOError("Failed to read old screen image at path: %s. Error: %s" % (old_screen_path, e))

        # 3. Compare them using the correct function: aircv.cal_rgb_confidence
        try:
            result = cal_rgb_confidence(old_screen, new_screen)
        except Exception as e:
            print("Could not compare images, likely due to different sizes. Error: %s" % e)
            raise AssertionError("%s Screens could not be compared)." % msg)

        # 检查图片尺寸是否一致
        # if old_screen.shape != new_screen.shape:
        #     raise ValueError("Images must have the same dimensions for comparison. "
        #                     "Old: %s, New: %s" % (old_screen.shape, new_screen.shape))
        # 生成并获取对比图的文件名
        old_screen, new_screen = self._equalize_image_heights(old_screen, new_screen)
        self._generate_diff_image(old_screen, new_screen)

        if result < threshold:
            set_step_traceback("%s: 图片差异过大:%s." % (msg, result))
            return False
        return True

    def _generate_diff_image(self, old_screen, new_screen, result, diff_threshold=10):
        """生成一张对比图，并高亮显示两张输入图片的差异之处。"""
        # 轻微高斯模糊减少噪点
        old_gray = cv2.cvtColor(old_screen, cv2.COLOR_BGR2GRAY)
        new_gray = cv2.cvtColor(new_screen, cv2.COLOR_BGR2GRAY)
        old_blur = cv2.GaussianBlur(old_gray, (5, 5), 0)
        new_blur = cv2.GaussianBlur(new_gray, (5, 5), 0)

        # 使用处理后的灰度图计算差异
        diff = cv2.absdiff(old_blur, new_blur)
        
        # 将差异大于可调阈值的像素变为白色，其余为黑色
        _, thresh = cv2.threshold(diff, diff_threshold, 255, cv2.THRESH_BINARY)
        
        # 放大差异区域，使其更容易连接成块
        dilated = cv2.dilate(thresh, None, iterations=5)
        # 找到差异区域的轮廓
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 在新的彩色截图上绘制差异区域的矩形框
        new_screen_with_rects = new_screen.copy()
        for contour in contours:
            # 忽略过小的噪点轮廓
            if cv2.contourArea(contour) < 20:
                continue
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(new_screen_with_rects, (x, y), (x + w, y + h), (0, 0, 255), 2)

        # 获取图片尺寸
        h, w, _ = old_screen.shape
        
        # 创建一个横向拼接的画布
        comparison_image = np.zeros((h + 40, w * 2, 3), dtype=np.uint8)
        
        # 粘贴旧图和新图
        comparison_image[40:, :w] = old_screen
        comparison_image[40:, w:] = new_screen_with_rects

        # 在图片上方添加标签
        cv2.putText(comparison_image, 'Before', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.putText(comparison_image, 'New', (w + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.putText(comparison_image, str(result), (2*w - 120, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        png_file_name = str(int(time.time())) + '_compare.png'
        png_path = os.path.join(ST.LOG_DIR, png_file_name)
        cv2.imwrite(png_path, comparison_image, [cv2.IMWRITE_PNG_COMPRESSION, 0])
        try_log_screen(comparison_image, png_path)

    def _equalize_image_heights(self, img1, img2):
        """比较两张图片的高度，并将较短的图片底部用白色填充，使之与较长的图片等高。"""
        h1, w1, _ = img1.shape
        h2, w2, _ = img2.shape

        # 如果高度或宽度不一致，则进行处理
        if h1 != h2 or w1 != w2:
            max_h = max(h1, h2)
            max_w = max(w1, w2)
            
            # 创建一个纯白色的背景画布
            padded_img1 = np.full((max_h, max_w, 3), 255, dtype=np.uint8)
            # 将原始图片粘贴到画布的左上角
            padded_img1[:h1, :w1] = img1

            # 对第二张图也执行同样操作
            padded_img2 = np.full((max_h, max_w, 3), 255, dtype=np.uint8)
            padded_img2[:h2, :w2] = img2
            
            return padded_img1, padded_img2
        
        # 如果尺寸一致，直接返回原图
        return img1, img2

    @logwrap
    def send_keys(self, *value):
        """向当前焦点元素输入文本。

        Args:
            *value: 要输入的字符串或按键序列 (如 Keys.CONTROL, 'c')。

        Example:
            ``element.click()``
            ``self.text("hello world")``
            ``self.text(Keys.CONTROL, "a")``
        """
        MODIFIER_KEYS = (Keys.CONTROL, Keys.SHIFT, Keys.ALT)
        actions = self.action_chains
        held_modifiers = []

        for key in value:
            if key in MODIFIER_KEYS:
                actions.key_down(key)
                held_modifiers.append(key)
            else:
                actions.send_keys(key)
                if held_modifiers:
                    for modifier in held_modifiers:
                        actions.key_up(modifier)
                        actions.pause(0.1)
                        
                    held_modifiers = []
        
        if held_modifiers:
            for modifier in held_modifiers:
                actions.key_up(modifier)
        actions.perform()
        time.sleep(0.5)
        return self._gen_screen_log()


    @logwrap
    def ocr_touch(self, text, offset=(0,0), timeout=ST.FIND_TIMEOUT):
        """使用OCR识别屏幕上的文字，并点击它。

        Args:
            text (str): 要点击的文字。
            offset(tuple): 偏移坐标(x,y)
            timeout (int): 识别超时时间。

        Returns:
            tuple: 被点击文字的坐标。
            
        Example:
            ``self.ocr_touch("登录")``
        """
        _pos = self.ocr_helper.find_text(text, offset, timeout=timeout)
        element_data = {'center': _pos, 'text': text}
        log_res = self._gen_screen_without_log()
        log_res["pos"] = [_pos]
        tmp_ele = OcrElement(self, element_data, log_res)
        tmp_ele.click()
        return _pos

    @logwrap
    def ocr_find(self, text, timeout=ST.FIND_TIMEOUT):
        """使用OCR查找屏幕上的文字。

        Args:
            text (str): 要查找的文字。
            timeout (int): 识别超时时间。

        Returns:
            bool: 如果找到文本则返回 True，否则返回 False。

        Example:
            ``self.ocr_find("登录")``
        """
        try:
            self.ocr_helper.find_text(text, timeout=timeout)
            set_step_log(f"页面OCR查找到文本: {text}")
            return True
        except:
            set_step_traceback(f"页面OCR未查找到文本: {text}")
            return False

    def ocr_result(self,screen=None):
        """获取当前屏幕上所有的OCR识别结果。"""
        elements =  self.ocr_helper.get_all_ocr_results(screen=screen)
        return  [element['text'] for element in elements if element.get('text')]


    def list_serial_ports(self):
        """列出所有当前已配置的串口及其状态。

        Returns:
            dict: 包含串口信息的字典。
        """
        if not self.serial_manager:
            set_step_traceback("串口RPC客户端未初始化。")
            return {"error": "RPC client not initialized."}
        try:
            # 直接调用服务器端的 list_serial_ports 方法
            return self.serial_manager.list_serial_ports()
        except Exception as e:
            set_step_traceback(f"调用服务器 list_serial_ports 失败: {e}")
            return {"error": str(e)}

    @logwrap
    def serial_open(self, port, baudrate=115200, timeout=0):
        """动态打开一个新的串口并进行管理。

        Args:
            port (str): 串口号 (如 'COM3' 或 '/dev/ttyUSB0')。
            baudrate (int): 波特率。
            timeout (int): 超时时间。

        Returns:
            bool: 成功返回True，失败返回False。
            
        Example:
            ``self.serial_open('COM3')``
        """
        if not self.serial_manager:
            set_step_traceback("串口RPC客户端未初始化。")
            return False
            
        log_dir = os.path.join(ST.PROJECT_ROOT, "result")
        ret = self.serial_manager.open_port(port, baudrate, timeout, log_dir)
        
        if ret:
            set_step_log(f"成功请求RPC服务器打开串口 {port} (波特率: {baudrate})")
        else:
            set_step_traceback(f"请求RPC服务器打开串口 {port} 失败")
        return ret

    @logwrap
    def serial_close(self, port=None):
        """关闭并移除一个已打开的串口。

        Args:
            port (str, optional): 要关闭的串口号。如果为None，则使用setting.json中的默认串口。

        Returns:
            bool: 成功返回True，失败返回False。
            
        Example:
            ``self.serial_close('COM3')``
        """
        if not self.serial_manager:
            set_step_traceback("串口RPC客户端未初始化。")
            return False

        if port is None:
            port = self.get_setting("default_serial")
            if not port:
                set_step_traceback("错误：未在 setting.json 中配置 default_serial。")
                return False

        ret = self.serial_manager.close_port(port)
        if ret:
            set_step_log(f"成功请求RPC服务器关闭串口 {port}")
        else:
            set_step_traceback(f"请求RPC服务器关闭串口 {port} 失败")
        return ret

    @logwrap
    def serial_login(self, password=None, port=None, timeout=10):
        """在串口中执行登录操作。

        Args:
            password (str): 登录密码。如果为None，会尝试从setting.json中读取。
            port (str, optional): 串口号。如果为None，则使用setting.json中的默认串口。
            timeout (int): 登录超时时间。

        Returns:
            bool: 登录成功返回True，否则返回False
            
        Example:
            ``self.serial_login(password="123456")``
        """
        if not self.serial_manager:
            set_step_traceback(f"串口RPC客户端未初始化。")
            return False
            
        if port is None:
            port = self.get_setting("default_serial")
            if not port:
                set_step_traceback("错误：未在 setting.json 中配置 default_serial。")
                return False
        
        if not password:
            password = self.get_setting("serial_passwd")
        if not password:
            set_step_traceback(f"错误: 未在 setting.json 中找到 serial_passwd 字段（串口 {port}）")
            return False
            
        result = self.serial_manager.login("root", password, port, timeout)
        if result:
            set_step_log(f"串口 {port} 登录成功")
        else:
            set_step_traceback(f"串口 {port} 登录失败")
        return result

    @logwrap
    def serial_send(self, command, port=None, wait=1):
        """
        向指定的串口发送一条命令。

        Args:
            command (str): 要发送的命令字符串 (会自动添加换行符)。
            port (str, optional): 串口号。如果为None，则使用setting.json中的默认串口。
            wait (float, optional): 发送命令后等待的时间（秒），让设备有时间执行。
            
        Returns:
            bool: 发送成功返回True，否则返回False。
            
        Example:
            ``self.serial_send("ifconfig")``
        """
        if not self.serial_manager:
            set_step_traceback(f"串口RPC客户端未初始化，跳过发送：{command}")
            return False

        if port is None:
            port = self.get_setting("default_serial")
            if not port:
                set_step_traceback("错误：未在 setting.json 中配置 default_serial。")
                return False
            
        ret = self.serial_manager.send_cmd(command, port)
        if not ret:
            set_step_traceback(f"向串口 {port} 发送命令: {command} 失败")
        else:
            set_step_log(f"向串口 {port} 发送命令: {command}")
            if wait > 0:
                time.sleep(wait)
        return ret

    @logwrap
    def serial_get(self, lines=None, duration=None, port=None):
        """获取最近的串口日志。

        Args:
            lines (int, optional): 获取的行数。
            duration (int, optional): 获取的时间范围（秒）。
            port (str, optional): 串口号。如果为None，则使用setting.json中的默认串口。

        Returns:
            str: 日志字符串。
            
        Examples:
            ``self.serial_get(lines=100)``
            ``self.serial_get(duration=5)``
        """
        if not self.serial_manager:
            set_step_traceback(f"串口RPC客户端未初始化，无法获取Log")
            return ""

        if port is None:
            port = self.get_setting("default_serial")
            if not port:
                set_step_traceback("错误：未在 setting.json 中配置 default_serial。")
                return ""
            
        logs = self.serial_manager.get_log(lines, duration, port)
        if not logs or logs == "串口未打开":
            set_step_traceback(f"获取串口 {port} 的日志失败，{logs}")
        else:
            set_step_log(f"获取串口 {port} 的日志:\n{logs}")
        return logs

    @logwrap
    def serial_find(self, pattern, lines=None, duration=None, port=None):
        """在最近的串口日志中搜索匹配正则表达式的内容。

        Args:
            pattern (str): 正则表达式模式。
            lines (int, optional): 搜索的行数范围。
            duration (int, optional): 搜索的时间范围（秒）。
            port (str, optional): 串口号。如果为None，则使用setting.json中的默认串口。

        Returns:
            list[str]: 匹配到的字符串列表。
        """
        if not self.serial_manager:
            set_step_traceback(f"串口RPC客户端未初始化，无法搜索日志")
            return []

        if port is None:
            port = self.get_setting("default_serial")
            if not port:
                set_step_traceback("错误：未在 setting.json 中配置 default_serial。")
                return []
            
        results = self.serial_manager.search_log(pattern, lines, duration, port)
        
        if results:
            matches = [res['match'] for res in results]
            log_parts = []
            for i, res in enumerate(results):
                log_parts.append(f"第{i+1}匹配项:{res['match']}\n{res['line']}\n上下文: \n{res['context']}\n")
            
            log_message = f"在串口 {port} 共找到 {len(matches)} 个包含 '{pattern}' 的匹配项:\n\n" + "\n\n".join(log_parts)
            set_step_log(log_message)
            return matches
        else:
            set_step_traceback(f"在串口 {port} 的指定范围内未找到包含 '{pattern}' 的日志")
            return []


    @logwrap
    def serial_wait_pattern(self, pattern, timeout=10, port=None):
        """等待串口日志中出现匹配指定正则表达式模式的内容。

        Args:
            pattern (str): 正则表达式模式。
            timeout (int): 等待的超时时间（秒）。
            port (str, optional): 串口号，如 'COM3'。如果为None，则使用setting.json中的默认串口。

        Returns:
            list[str]: 包含单个匹配字符串的列表，或空列表。
        """
        if not self.serial_manager:
            set_step_traceback("串口RPC客户端未初始化，跳过等待模式。")
            return []

        if port is None:
            port = self.get_setting("default_serial")
            if not port:
                set_step_traceback("错误：未在 setting.json 中配置 default_serial。")
                return []

        result = self.serial_manager.wait_for_log(pattern, port, timeout)

        if result:
            # result is a single dictionary
            match = result['match']
            log_message = f"在串口 {port} 匹配到表达式 '{pattern}':\n\n" + \
                          f"匹配内容: {result['match']}\n" + \
                          f"{result['line']}\n" + \
                          f"上下文:\n{result['context']}\n"
            set_step_log(log_message)
            
            # Return a list with the single match for compatibility
            return [match]
        else:
            set_step_traceback(f"串口 {port} 在 {timeout}s 内未捕捉到表达式 '{pattern}', 已超时")
            return []


    @logwrap
    def wifi_connect(self, ssid, password):
        """连接到指定的WiFi网络。

        Args:
            ssid (str): WiFi名称。
            password (str): WiFi密码。

        Returns:
            bool: 成功返回True，失败返回False。
            
        Example:
            ``self.wifi_connect("MyHomeWiFi", "password123")``
        """
        if self.wifi_manager:
            ret = self.wifi_manager.connect_wifi(ssid, password)
            if ret:
                set_step_log("已连接上无线:"+ssid)
            else:
                set_step_traceback("连接无线失败:"+ssid)
            return ret
        else:
            set_step_traceback("未在 setting.json 中配置无线网卡")
            return False

    @logwrap
    def wifi_disconnect(self):
        """断开当前的WiFi连接。

        Returns:
            bool: 成功返回True，失败返回False。
            
        Example:
            ``self.wifi_disconnect()``
        """
        if self.wifi_manager:
            ret = self.wifi_manager.disconnect_wifi()
            if ret:
                set_step_log("已成功断开无线")
            else:
                set_step_traceback("断开无线失败")
            return ret
        else:
            set_step_traceback("未在 setting.json 中配置无线网卡")
            return False

    @logwrap
    def get_ip(self, interface_type=None):
        """获取指定网络接口的IP地址。

        Args:
            interface_type (str): 网卡类型 ("wired", "wireless") 或网卡名称。

        Returns:
            str or None: IP地址字符串，如果找不到则返回None。
            
        Examples:
            ``self.get_ip("wired")``
            ``self.get_ip("wireless")``
        """
        if interface_type == "wired":
            interface_name = self.settings.get("wired_adapter")
        elif interface_type == "wireless":
            interface_name = self.settings.get("wireless_adapter")
        elif interface_type == None:
            interface_name = self.settings.get("wired_adapter")
        else:
            interface_name = interface_type

        if interface_name:
            ip = get_ip_address(interface_name)
            set_step_log("当前IP: "+ip)
            return ip
        else:
            set_step_traceback(f"未在 setting.json 中配置 {interface_type} 网卡。")
            return None
    
    @logwrap
    def ping(self, ip_address, count=5):
        """Ping一个指定的IP地址。

        Args:
            ip_address (str): 目标IP地址。
            count (int): Ping的次数。

        Returns:
            bool: Ping成功返回True，失败返回False。
            
        Example:
            ``self.ping("8.8.8.8")``
        """
        ret,msg =  ping(ip_address, count)
        if ret:
            set_step_log(f"ping成功，结果如下：\n\n {msg}")
        else:
            set_step_traceback(f"ping失败，结果如下：\n\n {msg}")
        return ret

    @logwrap
    def get(self, address):
        """在浏览器中访问指定的网址。

        Args:
            address (str): 目标URL地址。
            
        Example:
            ``self.get("https://www.google.com")``
        """
        super(WebChrome, self).get(address)
        time.sleep(2)
        self._gen_screen_log()

    @logwrap
    def back(self):
        """浏览器后退到上一个页面。

        Example:
            ``self.back()``
        """
        super(WebChrome, self).back()
        self._gen_screen_log()
        time.sleep(1)

    @logwrap
    def forward(self):
        """浏览器前进到下一个页面。

        Example:
            ``self.forward()``
        """
        super(WebChrome, self).forward()
        self._gen_screen_log()
        time.sleep(1)

    @logwrap
    def snapshot(self, filename=None):
        """截取当前浏览器可视区域的图像。

        Args:
            filename (str, optional): 保存截图的文件名。

        Returns:
            dict: 包含截图信息的字典。
            
        Example:
            ``self.snapshot(filename="homepage.png")``
        """
        return self._gen_screen_log(filename=filename)
    
    @logwrap
    def full_snapshot(self, filename=None, msg="", quality=90, max_height=12000):
        """截取整个网页的完整长图。通过滚动页面并拼接图片实现。

        Args:
            filename (str, optional): 保存截图的文件名。
            msg (str): 截图的描述信息。

        Returns:
            dict or None: 包含截图信息的字典，如果失败则为None。
            
        Example:
            ``self.full_snapshot(filename="full_page.png", msg="首页长截图")``
        """
        if ST.LOG_DIR is None:
            return None
        if not filename:
            png_file_name = f"{int(time.time())}_full.png"
            filepath = os.path.join(ST.LOG_DIR, png_file_name)
        else:
            filepath = os.path.join(ST.LOG_DIR, filename)
        image_parts, scroll_amount_used = self._scroll_and_capture()
        if not image_parts:
            set_step_log("Error: image parts is NULL.")
            return None
        if len(image_parts) == 1:
            final_image = image_parts[0]
        else:
            # Implement fallback logic
            # Step 1: Try the primary (more accurate) anchor-based method first
            detected_footer_height = self._detect_footer_height(image_parts[0], image_parts[1])
            final_image = self._stitch_images_with_anchor(image_parts,detected_footer_height)
            # Step 2: If the primary method fails, use the fallback scroll-based method
            if final_image is None:
                final_image = self._stitch_images_by_scroll(image_parts, scroll_amount_used, detected_footer_height)

        # Save and Log the final result
        if final_image is not None:
            cv2.imwrite(filepath, final_image)
            try_log_screen(final_image, filepath)
            return {"screen": filepath}
        else:
            set_step_traceback("Error: Stitching failed with both primary and fallback methods.")

    @logwrap
    def select_item(self, text, container_selector=None, timeout=10):
        """在一个`<ul>`列表中查找并选择一个包含指定文本的`<li>`条目。

        Args:
            text (str): 您想要选择的条目的文本。
            container_selector (str, optional): 一个XPath字符串，用于指定搜索范围的`<ul>`容器。
                                              如果页面上有多个列表，建议使用此参数以确保准确性。
            timeout (int): 等待元素出现的最长时间。
        
        Raises:
            NoSuchElementException: 如果在超时后未找到目标列表项。
        """
        print(f"准备选择列表项，文本包含: '{text}'")
        
        if container_selector:
            base_xpath = container_selector
        else:
            base_xpath = "//*[@role='listbox' or @class='su-dropdown-wrapper' or self::ul]"
            
        # 使用starts-with()进行模糊匹配，使用normalize-space()处理空格问题
        target_xpath = f"{base_xpath}//*[starts-with(normalize-space(), '{text}')]"

        try:
            wait = WebDriverWait(self, timeout)
            # 使用 presence_of_element_located，因为元素可能在屏幕外，但已存在于DOM中
            list_item = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
            # 使用JavaScript将其滚动到视野内
            self.execute_script("arguments[0].scrollIntoView({block: 'center'});", list_item)
            time.sleep(0.1)
            list_item.click()
            return self._gen_screen_log()
            
        except:
            err_msg = f"操作超时：在{timeout}秒内未能找到包含文本 '{text}' 的列表项。"
            print(err_msg)
            raise NoSuchElementException(err_msg)

    @logwrap
    def scroll(self, scroll_amount=0.25):
        """上下滚动页面。

        Args:
            scroll_amount (float): 滚动量，向下为正，向上为负，
                                 以视口高度的百分比表示 ±(0.0 to 1.0)。

        Example:
            ``self.scroll(0.5)``  # 向下滚动半个视口的高度
            ``self.scroll(-0.25)`` # 向上滚动四分之一个视口的高度
        """
        viewport_h_js = self.execute_script("return window.innerHeight")
        viewport_w_pixels = self.get_window_size()['width']
        scroll_pixels = int(viewport_h_js * scroll_amount)
        scroll_origin = ScrollOrigin.from_viewport(int(viewport_w_pixels / 2), int(viewport_h_js * 3 / 4))
        self.action_chains.scroll_from_origin(scroll_origin, 0, scroll_pixels).perform()
        time.sleep(0.5)
        return self._gen_screen_log()

    def _scroll_and_capture(self, scroll_amount=0.25, post_scroll_delay=0.3):
        """向下滚动页面并连续截图，直到页面底部。

        Args:
            scroll_amount (float): 每次滚动的量，以视口高度的百分比表示 (0.0 to 1.0)。
            post_scroll_delay (float): 每次滚动后的等待时间。
        
        Returns:
            tuple[list, int]: 截图列表和每次滚动的像素值。
        """
        self.execute_script("window.scrollTo(0, 0)")
        time.sleep(0.1)
        viewport_h_js = self.execute_script("return window.innerHeight")
        viewport_w_pixels = self.get_window_size()['width']
        saved_screenshot = []
        last_screenshot_data = None
        scroll_amount = int(viewport_h_js * scroll_amount)
        if viewport_h_js < 900:
            self.execute_script("document.body.style.zoom = '75%'")

        for i in range(30):
            current_screenshot_data = self.screenshot()
            if last_screenshot_data is not None and np.array_equal(last_screenshot_data, current_screenshot_data):
                break
            saved_screenshot.append(current_screenshot_data)
            last_screenshot_data = current_screenshot_data
            scroll_origin = ScrollOrigin.from_viewport(int(viewport_w_pixels / 2), int(viewport_h_js * 3 / 4))
            self.action_chains.scroll_from_origin(scroll_origin, 0, scroll_amount).perform()
            time.sleep(post_scroll_delay)
        
        self.execute_script("document.body.style.zoom = '100%'")
        return saved_screenshot, scroll_amount

    def _stitch_images_with_anchor(self, images, footer_height):
        """结合页脚检测，使用内容区域最底部上移一些的中心区域锚点来拼接图像。"""
        if not images or len(images) < 2:
            return None

        if footer_height < 64:
            footer_height = 64

        try:
            stitched_image = images[0]

            for i in range(len(images) - 1):
                image_top = stitched_image
                image_bottom = images[i + 1]
                # 1. 精确计算内容区域的高度
                h_top, w_top, _ = image_top.shape
                content_area_h = h_top - footer_height
                if content_area_h <= 60: # 内容区至少要比锚点+buffer高
                    print("内容区域过小，跳过锚点拼接。")
                    return None 
                content_top = image_top[:content_area_h, :]
                content_bottom = image_bottom[:content_area_h, :]
                # 2. 从内容区最底部上移几像素，并在此创建锚点
                anchor_y_end = int(content_area_h * 0.99)
                anchor_y_start = int(content_area_h * 0.80)
                anchor_x_start = int(w_top * 0.40)
                anchor_x_end = int(w_top * 0.60)
                anchor = content_top[anchor_y_start:anchor_y_end, anchor_x_start:anchor_x_end]
                # 3. 在下方图片的内容区域中寻找锚点
                result = cv2.matchTemplate(content_bottom, anchor, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                print(f"V5锚点法匹配度 ({max_val:.4f})。，{max_loc[1]}")
                # 4. 检查匹配质量
                if max_val < 0.95:
                    print(f"V5锚点法匹配度 ({max_val:.4f}) 过低，中止。")
                    return None
                # 5. 精确拼接
                top_part_to_keep = image_top[:anchor_y_end, :]
                match_y_end_in_bottom = max_loc[1] + (anchor_y_end - anchor_y_start)
                bottom_part_to_keep = image_bottom[match_y_end_in_bottom:, :]
                stitched_image = np.vstack((top_part_to_keep, bottom_part_to_keep))

            return stitched_image

        except Exception as e:
            print(f"V5锚点拼接过程中发生异常: {e}")
            return None

    def _stitch_images_by_scroll(self, images, scroll_amount, footer_height):
        """通过迭代拼接内容区域并单独查找处理最后一帧来构建完整页面截图。"""
        if not images or len(images) < 2 or scroll_amount <= 0:
            return None

        try:
            screenshot_h, _, _ = images[0].shape
            content_area_h = screenshot_h - footer_height - 5
            if content_area_h <= 0: return images[-1] # 如果没有内容区域，直接返回最后一张图

            stitched_content = images[0][:content_area_h, :]

            for i in range(1, len(images) - 1):
                current_content_area = images[i][:content_area_h, :]
                new_part = current_content_area[content_area_h - scroll_amount:, :]
                stitched_content = np.vstack((stitched_content, new_part))
            # [末尾拼接] 特殊处理最后一张图，以应对滚动高度不足的情况
            last_image = images[-1]
            last_content_area = last_image[:content_area_h, :]
            # 从已拼接图像的底部取一个高度为50像素的锚点
            stitched_h, stitched_w, _ = stitched_content.shape
            anchor_height = 50
            # 确保锚点高度不超过已拼接高度
            if stitched_h < anchor_height:
                anchor_height = stitched_h
            anchor = stitched_content[stitched_h - anchor_height:, :]
            # 在最后一张截图的内容区域中寻找这个锚点
            result = cv2.matchTemplate(last_content_area, anchor, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            final_new_part = None
            # 如果找到了高可信度的匹配点
            if max_val > 0.9:
                # 新增的内容就是匹配点Y坐标 + 锚点高度之后的所有部分
                print(f"末帧锚点法匹配度 ({max_val:.4f})")
                match_y = max_loc[1]
                final_new_part = last_content_area[match_y + anchor_height:, :]
            else:
                final_new_part = last_content_area[content_area_h - scroll_amount:, :]
            # 如果最后的新增部分有内容，则拼接到长图上
            if final_new_part.shape[0] > 0:
                stitched_content = np.vstack((stitched_content, final_new_part))
            # 5. 获取并拼接最终的页脚
            final_footer = images[-1][content_area_h:, :]
            final_image = np.vstack((stitched_content, final_footer))
            return final_image

        except Exception as e:
            print(f"基于滚动的拼接过程中发生异常: {e}")
            return None

    def _detect_footer_height(self, image1, image2, max_check_height=300):
        """估算页面中固定页脚的高度。"""
        h, w, _ = image1.shape
        check_height = min(h, max_check_height)
        strip_height = 5
        diff_threshold = 5

        for y in range(h, h - check_height, -strip_height):
            start_y = y - strip_height
            if start_y < 0:
                continue

            strip1 = image1[start_y:y, :]
            strip2 = image2[start_y:y, :]

            mean_diff = np.mean(cv2.absdiff(strip1, strip2))

            if mean_diff > diff_threshold:
                footer_height = h - start_y
                print(f"Footer boundary detected. Height: ~{footer_height}px")
                return footer_height

        entire_checked_region1 = image1[h - check_height:h, :]
        entire_checked_region2 = image2[h - check_height:h, :]
        total_mean_diff = np.mean(cv2.absdiff(entire_checked_region1, entire_checked_region2))

        if total_mean_diff < diff_threshold:
            print(f"Detected footer in the bottom: {check_height}px.")
            return check_height
        else:
            return 64 # default 64px

    @logwrap
    def _gen_screen_log(self, element=None, filename=None, ):
        """生成截图和日志信息。"""
        if ST.LOG_DIR is None:
            return None
        if not filename:
            png_file_name = str(int(time.time())) + '.png'
            png_path = os.path.join(ST.LOG_DIR, png_file_name)
            print("this is png path:", png_path)
            filename=png_path
        self.screenshot(filename)
        saved = {"screen": filename}
        if element:
            size = element.size
            location = element.location
            x = size['width'] / 2 + location['x']
            y = size['height'] / 2 + location['y']
            if "darwin" in sys.platform:
                x, y = x * 2, y * 2
            saved.update({"pos": [[x, y]]})
        return saved

    def _gen_screen_without_log(self, element=None, filename=None, ):
        """生成截图信息。"""
        if ST.LOG_DIR is None:
            return None
        if not filename:
            png_file_name = str(int(time.time())) + '.png'
            png_path = os.path.join(ST.LOG_DIR, png_file_name)
            print("this is png path:", png_path)
            filename=png_path
        self.screenshot(filename)
        saved = {"screen": filename}
        if element:
            size = element.size
            location = element.location
            x = size['width'] / 2 + location['x']
            y = size['height'] / 2 + location['y']
            if "darwin" in sys.platform:
                x, y = x * 2, y * 2
            saved.update({"pos": [[x, y]]})
        return saved

    def screenshot(self, file_path=None):
        """对当前浏览器窗口截图。
        
        Args:
            file_path (str, optional): 截图保存的路径。如果为None，则返回图像的numpy数组。

        Returns:
            np.ndarray or None: 如果file_path为None，返回截图的numpy数组。
        """
        if file_path:
            try:
                self.save_screenshot(file_path)
            except:
                """
                   由于chromedriver版本升级，出现screenshot时句柄失效导致截图失败。
                   触发说明：driver.back()后调用截图。
                """
                print("Unable to capture screenshot.")
        else:
            if not ST.LOG_DIR:
                file_path = "temp.png"
            else:
                file_path = os.path.join(ST.LOG_DIR, "temp.png")
            try:
                self.save_screenshot(file_path)
            except:
                pass
            screen = aircv.imread(file_path)
            return screen

    def get_latest_download_file(self):
        """
        在指定的下载目录中查找并返回最新修改的文件。

        Returns:
            str: 最新下载文件的完整路径。

        Raises:
            Exception: 如果下载目录为空或无法确定下载目录。
        
        Example:
            # 1. 点击下载按钮
            download_button.click()
            # 2. 等待几秒钟确保文件落地
            time.sleep(5) 
            # 3. 调用方法获取最新文件名
            downloaded_file = self.get_latest_downloaded_file()
            print(f"找到最新的文件是: {downloaded_file}")
        """
        download_dir = self.download_directory

        if not download_dir:
            raise Exception("错误：无法确定下载目录。请在初始化WebChrome时通过Options指定 'download.default_directory'。")

        files = os.listdir(download_dir)
        if not files:
            raise Exception(f"下载目录 '{download_dir}' 为空。")

        # 使用 os.path.getmtime 获取每个文件的最后修改时间，并找到最新的一个, 排除了子目录
        paths = [os.path.join(download_dir, basename) for basename in files if os.path.isfile(os.path.join(download_dir, basename))]
        
        if not paths:
            raise Exception(f"下载目录 '{download_dir}' 中没有找到任何文件。")
        latest_file_path = max(paths, key=os.path.getmtime)
        set_step_log(f"成功获取最新下载文件: {latest_file_path}")
        return latest_file_path

    def _get_left_up_offset(self):
        """获取浏览器视口左上角相对于整个屏幕的坐标偏移。"""
        window_pos = self.get_window_position()
        window_size = self.get_window_size()
        mouse = Controller()
        screen = self.screenshot()
        screen_size = get_resolution(screen)
        offset = window_size["width"] - \
                 screen_size[0], window_size["height"] - screen_size[1]
        pos = (int(offset[0] / 2 + window_pos['x']),
               int(offset[1] + window_pos['y'] - offset[0] / 2))
        return pos

    def _move_to_pos(self, pos):
        """移动系统鼠标到指定屏幕坐标。"""
        self.mouse.position = pos

    def _click_current_pos(self):
        """在当前鼠标位置执行一次左键单击。"""
        self.mouse.click(Button.left, 1)

    def to_json(self):
        """为logwrap中的json编码器添加此方法。"""
        return repr(self)


class Element(WebElement):
    def __init__(self, _obj, log):
        if selenium.__version__ >= "4.1.2":
            super(Element, self).__init__(parent=_obj._parent, id_=_obj._id)
        else:
            super(Element, self).__init__(parent=_obj._parent, id_=_obj._id, w3c=_obj._w3c)
        self.res_log = log

    @logwrap
    def text(self):
        text =  super(Element, self).text
        set_step_log(f'获取元素的值 (Selenium): {text}')
        return text

    @logwrap
    def click(self):
        """点击此Web元素，并自动记录日志和截图。

        Returns:
            dict: 包含截图和位置信息的日志字典。

        Example:
            ``element.click()``
        """
        super(Element, self).click()
        time.sleep(0.5)
        return self.res_log

    @logwrap
    def double_click(self):
        """点击此Web元素，并自动记录日志和截图。

        Returns:
            dict: 包含截图和位置信息的日志字典。

        Example:
            ``element.click()``
        """
        super(Element, self).click()
        time.sleep(0.1)
        super(Element, self).click()
        time.sleep(0.5)
        return self.res_log

    @logwrap
    def is_on(self):
        """
        检查当前元素是否处于“开启”状态。
        会查找元素内部的 <input type="checkbox"> 或 role="switch" 的元素。

        Returns:
            bool: 如果找到勾选的 checkbox 或 aria-checked="true" 的 switch，则返回 True；否则返回 False。
        """
        try:
            if (self.is_selected() or self.get_attribute('aria-checked') == 'true'):
                set_step_log("元素状态为开启。")
                return True
        except:
            pass

        try:
            checkbox = self.find_element(By.CSS_SELECTOR, 'input[type="checkbox"]')
            if checkbox.is_selected():
                set_step_log("找到已勾选的 checkbox，状态为开启。")
                return True
        except NoSuchElementException:
            pass

        try:
            switch = self.find_element(By.CSS_SELECTOR, '[role="switch"]')
            aria_checked = switch.get_attribute('aria-checked')
            if aria_checked == 'true':
                set_step_log("找到 aria-checked='true' 的 switch，状态为开启。")
                return True
        except NoSuchElementException:
            pass
        set_step_log("未找到开启状态的 checkbox 或 switch，返回状态为关闭。")
        return False

    @logwrap
    def send_keys(self, *value):
        """向此Web元素输入文本，并自动记录日志和截图。

        Args:
            *value: 要输入的文本序列。

        Returns:
            dict: 包含截图和位置信息的日志字典。

        Example:
            ``element.send_keys("some text")``
        """
        super(Element, self).send_keys(*value)
        time.sleep(0.5)
        return self.res_log
    
    @logwrap
    def select_item(self, text, timeout=10):
        """在当前元素（通常是下拉菜单触发器）下弹出的`<ul>`列表中选择一项。
        
        Args:
            text (str): 您想要选择的列表项的文本。
            timeout (int): 等待列表项出现的最长时间。
            
        Returns:
            dict: 包含截图和位置信息的日志字典。
            
        Raises:
            NoSuchElementException: 如果在超时后未找到目标列表项。
        """
        driver = self._parent
        base_xpath = "//*[@role='listbox' or @class='su-dropdown-wrapper' or self::ul]"
        # 使用starts-with()进行模糊匹配，使用normalize-space()处理空格问题
        target_xpath = f"{base_xpath}//*[starts-with(normalize-space(), '{text}')]"
        super(Element, self).click()
        try:
            wait = WebDriverWait(driver, timeout)
            # 使用 presence_of_element_located，因为元素可能在屏幕外，但已存在于DOM中
            list_item = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
            # 使用JavaScript将其滚动到视野内
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", list_item)
            time.sleep(0.1)
            res_log = driver._gen_screen_log(list_item)
            list_item.click()
            return res_log
        except:
            err_msg = f"操作超时：在{timeout}秒内未能找到包含文本 '{text}' 的列表项。"
            print(err_msg)
            raise NoSuchElementException(err_msg)
        
class OcrElement:
    def __init__(self, driver, element_data, log=None):
        self._driver = driver
        self._data = element_data
        self.res_log = log
        self._has_clicked = False
        self._element = None

        try:
            x, y = element_data.get('center')
            element = driver.execute_script("return document.elementFromPoint(arguments[0], arguments[1]);", x, y)
            self._element = Element(element, log)
        except:
            pass


    @property
    def center(self):
        """返回元素的中心坐标。"""
        return self._data.get('center')

    @logwrap
    def clear(self):
        """清理此元素。"""
        if self._element:
            return self._element.clear()

    @logwrap
    def text(self):
        """
        返回元素的识别文本。采用中心点确认法以提高准确性。

        Returns:
            str: 元素的文本内容。
        """
        if self.res_log.get('screen') and self.res_log.get('pos'):
            try_log_screen(filename=self.res_log.get('screen'), pos=[self.center])

        original_center = self.center
        if not original_center:
            text_content = self._data.get('text', '')
            set_step_log(f'获取元素的值：{text_content}')
            return text_content

        screen = self._driver.screenshot()
        h, w, _ = screen.shape
        y_buffer = 50
        min_x, max_x = int(0), int(w)
        min_y, max_y = int(original_center[1] - y_buffer), int(original_center[1] + y_buffer)
        min_x, min_y = max(0, min_x), max(0, min_y)
        max_x, max_y = min(w, max_x), min(h, max_y)
        
        if min_x >= max_x or min_y >= max_y:
            return self._data.get('text', '')

        element_roi = screen[min_y:max_y, min_x:max_x]
        try_log_screen(element_roi, pos=[[original_center[0],50]])
        ocr_results = self._driver.ocr_helper.ocr.ocr(element_roi, cls=False)
        found_text = None

        if ocr_results and ocr_results[0]:
            relative_center = (original_center[0] - min_x, original_center[1] - min_y)

            for line in ocr_results[0]:
                box_points = np.array(line[0], dtype=np.int32)
                text = line[1][0]
                
                distance_to_contour = cv2.pointPolygonTest(box_points, relative_center, True)
                if distance_to_contour >= 0:
                    found_text = text
                    self._data['text'] = found_text
                    break
            if found_text is None:
                for line in ocr_results[0]:
                    box_points = np.array(line[0], dtype=np.int32)
                    text = line[1][0]
                    distance_to_contour = cv2.pointPolygonTest(box_points, relative_center, True)
                    if distance_to_contour >= -10:
                        found_text = text
                        self._data['text'] = found_text
                        break
        if found_text is not None:
            set_step_log(f'获取元素的值 (刷新后): {found_text}')
            return found_text
        else:
            original_text = self._data.get('text', '')
            set_step_log(f'获取元素的值 (旧值): {original_text}')
            return original_text
    
    @logwrap
    def click(self):
        """点击此元素。"""
        if self._element:
            return self._element.click()

        if self.center:
            _pos =self.center
            x, y = _pos
            pos = self._driver._get_left_up_offset()
            pos = (pos[0] + x , pos[1] + y )
            self._driver._move_to_pos(pos)
            self._driver._click_current_pos()
            time.sleep(1)
            self.res_log["pos"] = [_pos]
            self._has_clicked = False
            return self.res_log
        else:
            raise ValueError("元素没有中心坐标，无法点击。")

    @logwrap
    def double_click(self):
        """点击此元素。"""
        if self._element:
            return self._element.double_click()

        if self.center:
            _pos =self.center
            x, y = _pos
            pos = self._driver._get_left_up_offset()
            pos = (pos[0] + x , pos[1] + y )
            self._driver._move_to_pos(pos)
            self._driver._click_current_pos()
            time.sleep(0.1)
            self._driver._click_current_pos()
            time.sleep(1)
            self.res_log["pos"] = [_pos]
            self._has_clicked = True
            screen = self._driver.screenshot()
            try_log_screen(screen, pos=[self.center])
            return self.res_log
        else:
            raise ValueError("元素没有中心坐标，无法点击。")


    @logwrap
    def is_on(self, threshold=0.8):
        """
        使用模板匹配判断开关是否开启 (推荐使用 find_template)。

        :param on_template_path: “开启”状态的模板图片路径。
        :param threshold: 匹配的置信度阈值。
        :return: True 如果开启, False 如果关闭。
        """
        if self.res_log.get('screen') and self.res_log.get('pos'):
            try_log_screen(filename=self.res_log.get('screen'), pos=[self.center])

        import base64
        from airtest.aircv.aircv import crop_image
        from airtest.aircv.template import find_template

        def decode_image(base64_string):
            """将Base64字符串解码为OpenCV图像对象。"""
            img_bytes = base64.b64decode(base64_string)
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        on_template1_base64 = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAASABIDAREAAhEBAxEB/8QAGAAAAwEBAAAAAAAAAAAAAAAABQcJCgb/xAAgEAABBQEAAwADAAAAAAAAAAADAQIEBQYHAAgSERMX/8QAGQEAAwEBAQAAAAAAAAAAAAAABQgJBgMH/8QAIxEAAgMBAAICAwADAAAAAAAAAgMBBAUGByEAERITFBUWIv/aAAwDAQACEQMRAD8Avb7B+wfbH9r6jAgdQ3VBWUG51OaqqrNai7z1XEq89dzaeA1sGnmw4z5D48MZJcsg3yJMl5ClI5XIiM/y/L89HPY7G4+bZdZzadt77dOvacbrVdb2zLXrYcBBsmACJgACIEYj69yB8weX/J5eTu7qVO76rJo5HVb2Jn5+JvamPRr0MfUtZtSIqZ1qsknEmsB2LBgTnuI2MOZmIjjP6R7TVuVrOjl6P2YWQmXZqetv5m41R6mbbwWJILFQMu2KKWFEaQavNHLAkGjzIf2U0WUARD/E8a267JjJwJvLrjYdVDOpC9aGT+InJAiJAp+4mIE4aIktn0ImsizP+6+eaWBR7Q+08lBzlnUZm0dez1O+3Ps6NUIcyvC7GgxdhcQJhJMSdRzE2a35MbXsKXoA5ToLHW8u5tqrh4y2+mwOP0FqQImAESxuc9XWU54gjRBhG+TJK5gmIjBtVGNRGoieLHtVVUdnWpIiYRT079VMEUkUKr2mqXBFPspgAGJKfcz7n38rvwGxd6HhOK39IgPR3OS5zYvmtYqWd3Tx6d20S1BEAsCe9kisYgQGYEYiIj5Ead0bP849lO9U3R8bB1fOtx0fd1G0qpVaBt8Gnk7Gxsq64z1r+I9pBlQirDt44Yk+KGwaIBWEBMFXWMNhl5VrV5Lmn5V9tLVzsnNfnvBxfzE8KCktRaR/0lgMH9iDI1mSpIhmCXLVMl5a7PI4vzZ5Zzez5qpv8b1PadXndNn2KSo1l5rukuXqWjj3/pN6q+sz+bRSuvbQq5AJYJqsrpXaqR7N2K465fxzuiAz2MzwFqcHh61Ghpsnnw/I4sSOALRALPKEQXWVh+phJZmNaxoYgYsYGhwMFGHWMYMrV+0X79LRd9lYu2i+5NhkUyULgiL9SvymAGZmZJhGZeX+S/JGl5E10tKurH5rGVOfyfLUYFeZz+Qv8QRXQlYrUdti1rm7c/WJ2GCIjC6yq6FaEeFgNF4jxyNJEQEiPyvnoDgMxwyhMHI1AyiKN6I4ZBva5j2ORHNc1WuRFRU8V/oyE+h3jAoIT2tQhIZiRISvPkSGY9TExMTEx6mPcfLB+KlNR4v8bocs1OTwXHqapgyDFNXz2cDFsAoggMDGRISiJEomJiJj4W0HKeXa2xfcarm2B01uUYgktdBj89c2JBAYgwifOsq6TJeMI0RgmOKrRsRGsRGoiecKu1s0VQilradNESRQmrftV1QRT9kULU0AiSn2UwP3M+59/CGxwPCdDdLS3+K5Lc0TBazv7HOY+ndNahgFLK1dpveQLCIFYyyRAYgRiIj6+CQcL4jFMKTG45yuPIARhgHBz3JBMEo3I8ZRFHUNeMg3IjmPY5rmuRHNVFRF87l0fQmJAe9tEBRIkJal4hIZj6kSGXzExMepiYmJj1PwerxV4vQ1bkeN+CS5RixTlcfzy2qYEwQMWwM6DAwKIISGYIZiJiYmPjU8C/N78//Z"
        on_template2_base64 = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAAWACgDAREAAhEBAxEB/8QAGwAAAgEFAAAAAAAAAAAAAAAACAkHAgMFBgr/xAAoEAACAgICAAUDBQAAAAAAAAACAwEEBQYHCAAJERJBExQVFiExMlH/xAAcAQACAQUBAAAAAAAAAAAAAAAHCAYBAgQFCQP/xAAtEQACAgIBAwMDAwQDAAAAAAACAwEEBQYRBxIhAAgTFCIxFVFhJDJBQmJxgf/aAAwDAQACEQMRAD8A6vO5PcnYtA2K1xTxTaRjs7jkInbdtlFW8/HPvVQspwmETZB9RVxVR6nZHIuU5tVrgqVArXKz3gYNC0Krk6oZrNATazSKKNGCNYtFZyBWLBBInK5MSFShIYOBkzk1mIyjHuT9yeZ1HMv0DQHqp5ampU7DsMqRabSbaQD14zGLeDa4WQrtWy5cYtpoNo164pspa0Fou7A87vaxx8z8qCbSkyFO/wC1VlRM/wAwtFfKqQof8BSwCPgY8FwdY1sRgYwGFmIjiO7GUjL/ANIkyRT/ADMzP8+kjb1e6ruYbT6l77BGUkUK27PIXEzPMwCk31qWP7CsBGPxERHrbuPt+7NcnbhhNH1Hlzli9nc9a+3qgzkncVVaylrN9zIXnxljmvQx9RTrlx0LYYoScJU50rSzBymM1DD0bGRvYPCLrVg7zmMTQIzKZgVqWPwR3NaciCx5iJIo7iEeSiQ6htvXDedjxera71D6gWsrlrHwoE912RaErACbYt2mxkD+GpTrgyzZZAGQqWXxrYyQWbatd6nbnTxNctg7U9iLuzAoDO1it7vVtfXa9sSQ/hsv+asXay2TIxD8imbADBEpEl7ACNrdqBvKKumaqunJTEA/GrO1Ic+J+oR9OCzmPP2qLtmeIkuOZ6EYb2/bNWx6izHXvrHazgrEisUNrtJw4WO2JIf03I/qbrSAPkY+W4qXDHJLVJSA5/Qt95K445KxfCvNWUq7bW22res8V8qVqNfDnsJ4evD8jq2045ExUq7FVqQNivYrkQ3xJIk65cuRKcXJ43E5XEO2DX0nSKkawzWFNhPirDy7VXKbS+86pnyJgURKp7pgVrX52+p7Zu2mbtR6ZdTbyNhTsKLb9C31FRWOLMljlfLdwWdpK4r18zXrxDkuTMjbGViTLNmzEgmDs7icthuwfL9XMg4LVjfNgy1f6wkJHic5eZmMIYe7+ySw96j9Eo9RlcDA/tHg/ag9FjV8EdeRkAxtVBds+IfWXFexE/8AKHrZ3R+/Prmh1zx+QxvWDqMjJCwXu2zL5BPyQUSWPylo8liyHu/Kyx1qr8cx9vZxEeI9QT4knoU+jm8vTN4TD9gwr5diFWM/pewYTAMeQBH5s7mGygrUZzEQ+xi8XlK6RiYNpuhAQRtESHPVGvYfq8miCIKuQq2LUDEz/TwuwmZmI/1FzkmU/gYHuniImYaj2eZTF43rACcialuy+s5fF4g2kIxGUKxjbwgBFMRDXUaF9Cxie5hNhQRJMgZfF4W311g9CL2VarK7/wBXtRxUi3bWc4YPcVpR6Hbr6fqVHIWdte0Q9WJpOrPQJmcCp32zRiSlBwM51ISRjNxvO5GjGu2aEkXgDv3mKCiMTPgmCYlxEcyPfEzx3Ryu/Wxi7+3dCtdoTDNhPqji9kBap7rCdb16pcfsLTEeTXWahqoIigQb8DBiS+I4G92U6l6j2CXVzIX51PfMZVmpU2RFMbtfJUg97EYzPUYdWO0hLTL7S6iwu5RhrY9LiICpFmpbte1iTRKvrca4+9lQmSslMniCdWZ2nAEQxHeshlbO2P7C+/169bPb5rvV8EZIbc6/tlFH09fNJrRaTdqjJGqjlqnyIJ6lsIvp7KnBYqww/FhUDX9L7d5anNwtYNfb+K2ogphTHZfbkNMPgmJDSrIKKfkBe2I+DnwUB6t67Ix3Uc1BceYFFEhif2gpyATMfzIj/wBelBb7JOqEMOE7HoTFQUws25HYUsIefEmoNZeIFMfkRayInxBT+fVdTy4Of8fbq36G68XUr1Kwm3Su1Nj3WtbqW6zBdXtVbCdGB1exXcANS5RgxTAFiyEhiYofVfWWga2Y/MsWwSBizqY8wMDiRMDEsjIkJDMiQlEwUTMTExPq6v7LertSwi3U2fRKtqq5VitZr5rZk2K9hJixL0OXqosU5LBFimrITWYiYFBREwceu6/3yxOJr4bIbl13zUrUFctjytfebWwAsBgBf9PH4PBYi5ZEYiZO1S9XnEm9hmREQ6tWumz3lYVQ2qvElJfSILGhVmZnmR5bZsvWEz/gGcDHgYiIiIaXDYf3YY/HqxtzZejmTkFimc1fTtNjMAAjAw3sp4rFY6y8RiJkrFaZaUdzjIiIplHingwtM2HL8j75tdvkrlnYKi6F7bchTVjqOExAzDf09qWFSba+GxIumSbKiFtwolsrqw+wlmmzWxxkKqMTjaQYnCVTlqqKmE1lh8+Pqr1gog7D5HwPdHC4nt5PtEonmgdKy1nMZHdNrz9nduoOYrjUt7DcrLp1cZjomGRh9exiiNOMx8M8slcwdgolnZXhrlH/AP/Z"
        on_template1 = decode_image(on_template1_base64)
        on_template2 = decode_image(on_template2_base64)

        screen = self._driver.screenshot()
        x_buffer = 150
        y_buffer = 20
        
        original_center = self.center
        min_x, max_x = int(original_center[0] - x_buffer), int(original_center[0] + x_buffer)
        min_y, max_y = int(original_center[1] - y_buffer), int(original_center[1] + y_buffer)
        rect = (min_x, min_y, max_x, max_y)
        
        h, w, _ = screen.shape
        if rect[0] >= w or rect[1] >= h or rect[2] <= 0 or rect[3] <= 0:
            return False # 元素在屏幕外
        cropped_image = crop_image(screen, rect)
        try_log_screen(cropped_image)
        if cropped_image is None or cropped_image.size == 0:
            return False # 裁剪区域为空
        match_result1 = find_template(cropped_image, on_template1, threshold=threshold)
        match_result2 = find_template(cropped_image, on_template2, threshold=threshold)
        set_step_log( {"on_template1":match_result2,"on_template2":match_result1} )
        if match_result1 or match_result2:
            return True
        else:
            return False

    @logwrap
    def send_keys(self, *value):
        """
        点击元素以确保焦点，然后输入文本，并返回关联的日志信息。
        """
        # if self._element:
        #     return self._element.send_keys(*value)

        if not self.center:
            raise ValueError("元素没有中心坐标，无法输入")
        skip_focus = getattr(self, "_has_clicked", False)
        need_click = False if skip_focus and self._active_element_is_editable() else True

        if need_click:
            self.click()
        self._has_clicked = False

        MODIFIER_KEYS = (Keys.CONTROL, Keys.SHIFT, Keys.ALT)
        actions = self._driver.action_chains
        held_modifiers = []

        for key in value:
            if key in MODIFIER_KEYS:
                actions.key_down(key)
                held_modifiers.append(key)
            else:
                actions.send_keys(key)
                if held_modifiers:
                    for modifier in held_modifiers:
                        actions.key_up(modifier)
                        actions.pause(0.1)
                    held_modifiers = []
        if held_modifiers:
            for modifier in held_modifiers:
                actions.key_up(modifier)

        actions.perform()
        time.sleep(0.5)
        screen = self._driver.screenshot()
        try_log_screen(screen, pos=[self.center])
        self.res_log["pos"] = [self.center]
        return self.res_log

    def _active_element_is_editable(self):
        try:
            return bool(self._driver.execute_script("""
                const el = document.activeElement;
                if (!el) return false;
                const tag = el.tagName ? el.tagName.toLowerCase() : '';
                if (tag === 'input') {
                    const type = (el.type || '').toLowerCase();
                    const nonEditableTypes = ['button', 'submit', 'reset', 'checkbox', 'radio', 'file', 'image', 'color', 'range', 'hidden'];
                    if (nonEditableTypes.indexOf(type) !== -1) {
                        return false;
                    }
                    return !el.disabled && !el.readOnly;
                }
                if (tag === 'textarea') {
                    return !el.disabled && !el.readOnly;
                }
                if (el.isContentEditable) {
                    const attr = el.getAttribute('contenteditable');
                    return attr !== 'false';
                }
                return false;
            """))
        except Exception:
            return False

    @logwrap
    def select_item(self, text, timeout=10):
        """在当前元素（通常是下拉菜单触发器）下弹出的`<ul>`列表中选择一项。"""


        driver = self._driver
        base_xpath = "//*[@role='listbox' or @class='su-dropdown-wrapper' or self::ul]"

        # 使用starts-with()进行模糊匹配，使用normalize-space()处理空格问题
        target_xpath = f"{base_xpath}//*[starts-with(normalize-space(), '{text}')]"
        self._element.click() if self._element else self.click()
        try:
            wait = WebDriverWait(self._driver, timeout)
            # 使用 presence_of_element_located，因为元素可能在屏幕外，但已存在于DOM中
            list_item = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
            # 使用JavaScript将其滚动到视野内
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", list_item)
            time.sleep(0.5)
            res_log = driver._gen_screen_log(list_item)
            list_item.click()
            return res_log
            
        except:
            err_msg = f"操作超时：在{timeout}秒内未能找到包含文本 '{text}' 的列表项。"
            print(err_msg)
            raise NoSuchElementException(err_msg)

    def __repr__(self):
        return f'<OcrElement text="{self.text()}" center={self.center}>'
