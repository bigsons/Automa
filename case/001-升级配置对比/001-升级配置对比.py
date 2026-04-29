# -*- encoding=utf8 -*-
__author__ = "Your Name"
__brief__ = "升级软件到自测目标版本，检查"
__desc__ = "本字段用于具体描述脚本的测试过程，测试点"
import sys
from airtest.core.api import *
log(sys.path)
from utils.common import *

driver = WebChrome()
result = {}
setting = driver.get_setting()
path = setting.get("model_path")
version = setting.get("model_version")

try:
    dic = parse_upfile(path,version)
    log(dic)

    # 登录
    # driver.serial_login(setting["serial_passwd"])
    # device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
    # driver.web_login(device_ip, passwd=setting["passwd"])
    # driver.web_skip_qs()

    
except Exception as e:
    log(e) and print(f"测试执行过程中发生异常")

finally:
    driver.assert_custom(all(result.values()), dic, msg="脚本执行结果汇总")
    driver.quit()


