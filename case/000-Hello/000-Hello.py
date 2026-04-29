# ================================================================================ #
# -*- encoding=utf8 -*-
# 脚本作者
__author__ = "Your Name"
# 脚本必选的资源，目前可用的有：串口设备。无线网卡，有线网卡
__req__ = ["default_serial","wireless_adapter"]
# 脚本简介，将显示在AutoTest工具和报告中
__brief__ = "这是一个简单的测试脚本示例 【串口/无线】"
# 脚本详细描述，此处介绍脚本的测试思路，测试过程，测试点供使用者参加
__desc__ = """本字段用于具体描述脚本的测试过程，测试点
            脚本描述支持多行，可在此详细描述测试步骤，测试目标"""
# ================================================================================ #

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
    driver.web_skip_qs()

    # 截图客户端页面
    driver.find("Clients").click()
    clients_snapshot = driver.snapshot()

    # 配置无线
    driver.find("Wireless").click()
    driver.find("2.4 GHz Advanced Settings").click()
    driver.find("Network Name",["right"]).send_keys(Keys.CONTROL, 'a', Keys.BACK_SPACE, "Autotest-2.4G_"+str(random.randint(0,99)))
    driver.ocr_touch("Password:",(300,0))
    driver.send_keys(Keys.CONTROL, 'a', Keys.BACK_SPACE, "12345670")
    driver.send_keys(Keys.TAB)
    driver.find("Channel Width",offset=(250,0)).select_item("40 MHz")
    driver.find("SAVE").click()
    driver.find("OK").click()

    time.sleep(2)

    # 截图功能
    driver.web_page("firmware")
    driver.snapshot()
    driver.full_snapshot()

    # 连接无线
    driver.web_page("/")
    driver.airtest_touch(Template(r"tpl1759081893976.png"))
    driver.find("5 GHz",["的右边","的右边"]).click() # 点开小眼睛
    ssid_5g = driver.find("5 GHz",["的右边"]).text().replace(" ","_")
    ssid_5g_pswd = driver.find("5 GHz",["的右边","的右边"]).text()
    driver.wifi_connect(ssid_5g, ssid_5g_pswd)

    # 网络测试
    time.sleep(5)
    pc_ip = driver.get_ip("wired")
    result["point1"] = driver.ping(device_ip, pc_ip)

    # 串口操作
    driver.serial_send("ifconfig")
    driver.serial_get(duration=5)
    driver.serial_find(r"inet(?: addr)?[:=\s]+(\d+\.\d+\.\d+\.\d+)",duration=5) #查历史的Log匹配“pattern”
    driver.serial_get(lines=50)
    result["point2"] = driver.serial_wait_pattern("ip",timeout=5) #查接下来Log中是否有匹配“pattern”

    # 断言测试点
    driver.find("Clients").click()
    driver.assert_screen(clients_snapshot["screen"],msg="比较客户端页面变化") #测试点
    driver.assert_custom(result,"可以自定义一段Log",True,"修改WIFI名并连接5G") #测试点

except Exception as e:
    # 建议捕获异常，以便在出错时进行额外的诊断或标记
    log(e) and print(f"测试执行过程中发生异常{e}")

finally:
    # 汇总该脚本的测试点，得到脚本最终执行结果并记录到报告中
    driver.assert_custom(result and all(result.values()), result, msg="脚本执行结果")
    # 4. (推荐) 在脚本末尾关闭浏览器，释放资源
    driver.quit()


