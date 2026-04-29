# -*- encoding=utf8 -*-
# ================================================================================ #
__author__ = "Your Name"
__brief__ = "测试恢复出厂后的首次配置 【无线】"
__desc__ = """脚本逻辑与测试步骤：
            0. 检查软件是否待测版本，恢复出厂
            1. 设置密码、时区, 检查UCI配置
            2. 设置拨号方式: DHCP 和 PPPoE, 检查LAN-WAN 连通性正常
            3. 设置 SSID 密码，开关 Smart Connect, 检查WLAN-WAN 连通性
            4. 云账号：初始绑定"""
__req__ = ["wireless_adapter"]
# ================================================================================ #

from utils.common import *
REQUIRED_RESOURCES_CHECK(__req__)

driver = WebChrome()
result = {}
setting = driver.get_setting()
cur_version = parse_version(setting.get("model_version", None))
upfile_list = parse_upfile(setting.get("model_path", None) ,cur_version)

try:
    driver.serial_login(setting["serial_passwd"])
    device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
    driver.serial_send("cat /etc/partition_config/soft-version")
    if not driver.serial_find(cur_version ,duration=2):
        log("升级软件到待测版本")
        driver.web_login(device_ip, passwd=setting["passwd"])
        driver.web_skip_qs()
        driver.web_upgrade(upfile_list["current_version"][0])
        time.sleep(180)

    # # 恢复出厂
    driver.serial_login(setting["serial_passwd"])
    device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
    driver.web_login(device_ip, passwd=setting["passwd"])
    driver.web_skip_qs()
    driver.web_factory_restore()
    time.sleep(120)
    for _ in range(60):
        if driver.ping(device_ip):
            break

    # QS流程
    driver.web_page("quickSetup")
    qs_steps = {"step_count":0}
    while True:
        time.sleep(2)
        ocr_result = " ".join(driver.ocr_result())
        if "Select your Time Zone" in ocr_result and not qs_steps.get("time_zone",False):
            driver.find("Time Zone:",["right"]).select_item("(UTC+08:00) Beijing")
            driver.find("NEXT").click()
            qs_steps["time_zone"] = True 
            qs_steps["step_count"] += 1

        elif "Combo Port" in ocr_result and not qs_steps.get("combo_select",False):
            driver.find("NEXT").click()
            qs_steps["combo_select"] = True 
            qs_steps["step_count"] += 1

        elif "Select Connection Type" in ocr_result and not qs_steps.get("bohao_select",False):
            driver.find("Dynamic IP").click()
            driver.find("NEXT").click()
            time.sleep(2)
            if "Router MAC Address" in " ".join(driver.ocr_result()):
                driver.find("NEXT").click()
            qs_steps["bohao_select"] = True 
            qs_steps["step_count"] += 1

        elif "Internet Port Disconnected" in ocr_result:
            driver.assert_custom(False,"WAN口未插入",True,"检查WAN口连接")

        elif "Personalize Wireless Settings" in ocr_result and not qs_steps.get("Wireless_Settings",False):
            if True != driver.find("Smart Connect:",["right"]).is_on():
                result["qs_smart_connect_test"] = False # smart_connect要求默认打开
                driver.find("Smart Connect:",["right"]).click()
            driver.find("Smart Connect:",["right"]).click()
            input_elements = driver.find_elements(By.XPATH, "//input[@type='text']")
            if not input_elements:
                driver.assert_custom(False,"输入默认SSID和密码错误",True,"设置无线配置")
            for i, input_element in enumerate(input_elements):
                try:
                    input_element.send_keys("Autotest-WIFI-setting"+str(random.randint(0,99)))
                except Exception as e:
                    print(f"向第 {i+1} 个密码框输入时发生错误: {e}")
            driver.send_keys()
            driver.find("//body").click()
            driver.find("NEXT").click()
            qs_steps["Wireless_Settings"] = True 
            qs_steps["step_count"] += 1

        elif "Connection Test" in ocr_result and not qs_steps.get("Connection_Test",False):
            time.sleep(100)
            if "No Internet Connection" in driver.ocr_result():
                driver.find("SKIP").click()
                result["internet_test"] = False
            qs_steps["Connection_Test"] = True 
            qs_steps["step_count"] += 1

        elif "Keep your router updated" in ocr_result and not qs_steps.get("auto_update",False):
            driver.find("NEXT").click()
            qs_steps["auto_update"] = True 
            qs_steps["step_count"] += 1

        elif "All set and help us improve" in ocr_result and not qs_steps.get("UEIP",False):
            driver.find("ACCEPT & JOIN").click()
            qs_steps["UEIP"] = True 
            qs_steps["step_count"] += 1
            break

        elif "Success!" in ocr_result and not qs_steps.get("summary_tips",False):
            driver.scroll(0.5)
            time.sleep(2)
            driver.find("NEXT").click()
            qs_steps["summary_tips"] = True 
            qs_steps["step_count"] += 1

        else:
            try:
                qs_steps["step_count"] += 1
                driver.assert_custom(False, "这个步骤重复或不在预先定义的QS步骤流程中，请手动检查是否合预期", True, msg="未定义的QS步骤")
            except:
                pass
            driver.find("//*[normalize-space()='NEXT' or normalize-space()='SKIP']").click()
            if qs_steps["step_count"] > 12:
                break

    log(qs_steps)

except Exception as e:
    log(e) and print(f"测试执行过程中发生异常")

finally:
    driver.assert_custom(result and all(result.values()), result, msg="脚本执行结果汇总")
    driver.quit()

