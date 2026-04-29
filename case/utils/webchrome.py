import re
import random
from airtest.core.api import *
from selenium.webdriver.common.keys import Keys
from tp_autotest.proxy import WebChrome as OriginalWebChrome
from selenium.webdriver.common.by import By
from airtest.core.helper import logwrap
from tp_autotest.utils.airtest_api import set_step_log, set_step_traceback

# 二封 WebChrome 类，继承了原始类的所有功能，并封装一些机型使用的接口
# 考虑到不同机型可能会有差异，此部分内容从tp-airtest-selenium里抽离，在此处继承WebChrome类方便大家修改
class WebChrome(OriginalWebChrome):
    """
    继承 tp_autotest 原始 WebChrome 的WebChrome类，
    """
    def __init__(self, executable_path=None, chrome_options=None):
        super().__init__(executable_path=executable_path, chrome_options=chrome_options)
        super().implicitly_wait(2)

    @logwrap
    def web_page(self, text):
        if "" == text or "/" == text:
            text = "networkMap"
        current_url = self.current_url
        base_url = current_url.split('#')[0]
        new_url = f"{base_url}#{text}"
        print(f"跳转到子页面: {new_url}")
        self.get(new_url)
        self.switch_to.active_element.send_keys(Keys.ESCAPE)

    @logwrap
    def web_login(self, url="http://192.168.0.1", passwd="admin123"):
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        self.get(url)
        self.get(url)
        if url.startswith(('https://')):
            try:
                self.find_element(By.ID, "details-button").click()
                self.find_element(By.ID, "proceed-link").click()
                time.sleep(2)
                self.find_element(By.XPATH, f"//*[normalize-space()='Local Management via HTTPS is disabled. Please access the device via HTTP.']")
                http_url = url.replace('https://', 'http://')
                self.get(http_url)
            except:
                pass

        if 'welcome' in self.current_url or 'onboarding' in self.current_url:
            https_url = url.replace('http://', 'https://')
            self.get(https_url)
            try:
                self.find_element(By.ID, "details-button").click()
                self.find_element(By.ID, "proceed-link").click()
                time.sleep(2)
            except:
                pass

        try:
            self.switch_to.active_element.send_keys(Keys.ESCAPE) # 跳过语言切换弹窗
            self.find_element_by_xpath("//*[@data-cy='pcCurrentLanguageSelect' or @id='login-lan-cb']").select_item("English")
            sleep(5)
        except Exception as e:
            pass

        # passwd_elements = self.find_elements_by_xpath("//input[contains(@data-cy, 'password') or contains(@aria-label, 'password')]")
        passwd_elements = self.find_elements(By.XPATH, "//input[@type='password']")
        if not passwd_elements:
            return False

        for i, input_element in enumerate(passwd_elements):
            try:
                input_element.send_keys(passwd)
            except Exception as e:
                print(f"向第 {i+1} 个密码框输入时发生错误: {e}")
        self._gen_screen_log()
        if passwd_elements:
            self.send_keys(Keys.ENTER)

        time.sleep(5)
        self.send_keys(Keys.ESCAPE) # 跳过fing或tplink登录弹窗
        self.send_keys(Keys.ESCAPE) # 跳过fing或tplink登录弹窗

    @logwrap
    def web_skip_qs(self):
        if "quickSetup" in self.current_url:
            self.web_page("")
            try:
                self.find_element(By.XPATH, '//*[normalize-space()="Exit Setup"]').click()
                self.find_element(By.XPATH, '//*[normalize-space()="EXIT"]').click()
            except:
                pass
            time.sleep(2)
            self.switch_to.active_element.send_keys(Keys.ESCAPE) # 跳过fing或tplink登录弹窗
            time.sleep(0.5)
            self.switch_to.active_element.send_keys(Keys.ESCAPE) # 跳过fing或tplink登录弹窗
        self._gen_screen_log()

    @logwrap
    def web_backup(self):
        self.web_page("backupRestore")
        self.find_element_by_text("BACK UP").click()
        print("备份当前配置文件")
        time.sleep(10)
        return self.get_latest_download_file()

    @logwrap
    def web_restore(self, text):
        self.web_page("backupRestore")
        self.find_element(By.XPATH, "//input[@type='file']").send_keys(text)
        self.find_element_by_text("RESTORE").click()
        self.find_element(By.XPATH, "//*[@role='dialog' or @id='msg-boxs-container' or @class='su-modal-wrap']//*[normalize-space()='RESTORE']").click()
        print(f"导入配置文件：{text}")
        try:
            self.find_element_by_text("Restoring...")
            return True
        except:
            self.find_element(By.XPATH, "//*[@role='dialog' or @id='msg-boxs-container' or @class='su-modal-wrap']//button")[-1].click()
            return False

    @logwrap
    def web_factory_restore(self):
        self.web_page("backupRestore")
        self.find_element_by_text("FACTORY RESTORE").click()
        time.sleep(1)
        self.find_element(By.XPATH, "//*[@role='dialog' or @id='msg-boxs-container' or @class='su-modal-wrap']//*[normalize-space()='RESTORE']").click()
        print("设备恢复默认配置")
        try:
            self.find_element_by_text("Restoring...")
            return True
        except:
            return False

    @logwrap
    def web_upgrade(self, text):
        self.web_page("firmware")
        self.find_element(By.XPATH, "//input[@type='file']").send_keys(text)
        self.find_element_by_text("UPDATE").click()
        self.find_element(By.XPATH, "//*[@role='dialog' or @id='msg-boxs-container' or @class='su-modal-wrap']//*[normalize-space()='UPDATE']").click()
        # self.find_element_by_ocr("UPDATE").click()
        print(f"升级软件：{text}")
        try:
            self.find_element_by_text("Upgrading...")
            return True
        except:
            self.find_element_by_text("CANCEL").click()
            return False

    @logwrap
    def web_switch_router(self):
        self.web_page("operationMode")
        self.find_element_by_text("Wireless Router Mode").click()
        time.sleep(0.5)
        try:
            self.find_element_by_xpath("//*[@data-cy='footerSaveBtn']").click()
            self.find_element_by_text("REBOOT").click()
            self.find_element_by_text("CONTINUE").click()
            print("设备切换到路由模式")
        except:
            self.find_elements(By.XPATH, "//*[@role='dialog' or @id='msg-boxs-container' or @class='su-modal-wrap']//button")[-1].click()
            return False
        
        return True

    @logwrap
    def web_switch_ap(self):
        self.web_page("operationMode")
        self.find_element_by_text("Access Point Mode").click()
        time.sleep(0.5)
        try:
            self.find_element_by_xpath("//*[@data-cy='footerSaveBtn']").click()
            self.find_element_by_text("REBOOT").click()
            self.find_element_by_text("CONTINUE").click()
            print("设备切换到AP模式")
        except:
            self.find_elements(By.XPATH, "//*[@role='dialog' or @id='msg-boxs-container']//button")[-1].click()
            return False
        
        return True

    @logwrap
    def serial_getip(self, port=None, prefix="br-lan", return_duration=3, msg="串口获取br-lan IP"):
        """Return the IPv4 address found within six lines after `br-lan` in `ifconfig` output."""
        ret = self.serial_send("ifconfig", port=port)
        if ret:
            log_text = self.serial_get(duration=return_duration, port=port) or ""
        else:
            return None

        lines = log_text.splitlines()
        ip_pattern = re.compile(r"inet(?: addr)?[:=\s]+(\d+\.\d+\.\d+\.\d+)")
        for idx, line in enumerate(lines):
            if prefix not in line:
                continue
            for candidate in lines[idx + 1: idx + 7]:
                match_line = ip_pattern.search(candidate)
                if not match_line:
                    continue
                ip_addr = match_line.group(1)
                if ip_addr.startswith("127."):
                    continue
                set_step_log(f"Serial br-lan IP address: {ip_addr}")
                return ip_addr
            break
        set_step_traceback("Serial get br-lan IP failed")
        return None


if __name__ == '__main__':
    pass