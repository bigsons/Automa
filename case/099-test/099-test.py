# -*- encoding=utf8 -*-
# 脚本作者
__author__ = "Your Name"
# 脚本简介，将显示在AutoTest工具和报告中
__brief__ = "这是一个简单的测试脚本示例 【串口/无线】"
# 脚本详细描述，此处介绍脚本的测试思路，测试过程，测试点供使用者参加
__desc__ = """本字段用于具体描述脚本的测试过程，测试点
            脚本描述支持多行，可在此详细描述测试步骤，测试目标"""
# 脚本必选的资源，目前可选有：串口设备。无线网卡，有线网卡
__req__ = ["default_serial","wireless_adapter"]

# 导入项目配置接口
from utils.common import *
REQUIRED_RESOURCES_CHECK(__req__)

# 1. 初始化Airtest和WebChrome驱动
result = {}
driver = WebChrome()

# 2. (可选) 从配置文件获取测试数据
setting = driver.get_setting()

# 3. 编写测试步骤，并使用try...finally确保资源释放
try:
    # 登录
    driver.serial_login(setting["serial_passwd"])
    device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
    driver.web_login(device_ip, passwd=setting["passwd"])
    driver.web_page("wirelessBasic")
    driver.scroll(0.25)
    driver.finds("Network Name (SSID):",offset=(200,0))[1].clear()
    driver.finds("Network Name (SSID):",offset=(200,0))[1].send_keys("12345678")


except Exception as e:
    # 建议捕获异常，以便在出错时进行额外的诊断或标记
    log(e) and print(f"测试执行过程中发生异常{e}")

finally:
    # 汇总该脚本的测试点，得到脚本最终执行结果并记录到报告中
    driver.assert_custom(result and all(result.values()), result, msg="脚本执行结果")
    # 4. (推荐) 在脚本末尾关闭浏览器，释放资源
    driver.quit()


