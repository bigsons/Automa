# -*- encoding=utf8 -*-
# ================================================================================ #
__author__ = "Your Name"
__brief__ = "从历史版本升级到当前版本，从当前版本回退到历史版本 【串口】"
__desc__ = """脚本逻辑与测试步骤：
            0. 准备: 将历史版本、提测版本、云升级陪测版本升级软件放入UI首页选择的软件路径
            1. 检查当前软件是否提测版本，如果不是则升级到提测版本
            2. 将软件从当前版本逐一降级到历史版本、再从历史版本升级回当前提测版本
            3. 如果软件路径里有2048软件, 将product-info改成SG 使用2048软件重复以上逻辑"""
__req__ = ["default_serial"]
# ================================================================================ #

from utils.common import *
REQUIRED_RESOURCES_CHECK(__req__)

driver = WebChrome()
result = {}
setting = driver.get_setting()
cur_version = parse_version(setting.get("model_version", None))
upfile_list = parse_upfile(setting.get("model_path", None) ,cur_version)
log("旧升新版本：\n" + str(upfile_list["history_version"]))

try:
    driver.serial_login(setting["serial_passwd"])
    device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
    driver.serial_send("cat /etc/partition_config/soft-version")
    if not driver.serial_find(cur_version ,duration=2):
        log("升级软件到待测版本")
        driver.web_login(device_ip, passwd=setting["passwd"])
        driver.web_skip_qs()
        driver.web_backup() # 备份当前配置
        driver.web_upgrade(upfile_list["current_version"][0])
        time.sleep(180)

    for upfile in upfile_list["history_version"]:
        version = parse_version(upfile)
        result_str = f"{version}_up_test"
        result[result_str] = False
        driver.serial_login(setting["serial_passwd"])
        device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
        driver.web_login(device_ip, passwd=setting["passwd"])
        driver.web_skip_qs()
        # 先降级到某个已发布版本
        if (cur_version[:4] != version[:4]):
            driver.serial_send("rm -f /tp_data/soft-version")
            driver.serial_send("sed -i 's/soft_ver:[0-9]*\.[0-9]*\.[0-9]* /soft_ver:1.0.0 /g' /etc/partition_config/soft-version")
        driver.web_upgrade(upfile)
        time.sleep(5)
        if (cur_version[:4] != version[:4]):
            driver.serial_send("nvrammanager -e -p user-config") # 跨大版本降级时清配置防止意外Bug

        # 等待设备启动
        time.sleep(120)
        driver.serial_login(setting["serial_passwd"])
        driver.serial_send("cat /etc/partition_config/soft-version")
        if not driver.serial_find(version ,duration=2):
            raise RuntimeError("降级失败")

        device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
        driver.web_login(device_ip, passwd=setting["passwd"])
        driver.web_skip_qs()

        # 升级到提测版本
        if not driver.web_upgrade(upfile_list["current_version"][0]):
            raise RuntimeError("升级到目标版本失败")
        time.sleep(120)
        for _ in range(60):
            if driver.ping(device_ip):
                break
            
        driver.serial_login(setting["serial_passwd"])
        driver.serial_send("cat /etc/partition_config/soft-version")
        if not driver.serial_find(cur_version ,duration=2):
            raise RuntimeError("升级到目标版本失败")
        
        device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
        driver.web_login(device_ip, passwd=setting["passwd"])
        driver.web_skip_qs()
        driver.web_page("firmware")
        if cur_version == parse_version(driver.find("Firmware Version",["right"]).text()):
            result[result_str] = True
        driver.assert_custom(result[result_str], "", msg=f"版本{version}旧升新")

    if len(upfile_list["current_version"]) > 1 and upfile_list["current_version"][1]:
        # 把国家码改为SG
        if "SG" in setting.get("COUNTRY",[]):
            driver.serial_send("cp /tp_data/product-info /tp_data/product-info_bk; cp /etc/partition_config/product-info /tp_data/")
            driver.serial_send("sed -i 's/special_id:[0-9]\{8\}/special_id:53470000/g' /tp_data/product-info && sed -i 's/country:.*/country:SG/g' /tp_data/product-info")

        for upfile in upfile_list["history_version"]:
            version = parse_version(upfile)
            result_str = f"{version}_up_test"
            result[result_str] = False
            driver.serial_login(setting["serial_passwd"])
            device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
            driver.web_login(device_ip, passwd=setting["passwd"])
            driver.web_skip_qs()
            # 先降级到某个已发布版本,SG需要强制降级
            driver.serial_send("rm -f /tp_data/soft-version")
            driver.serial_send("sed -i 's/soft_ver:[0-9]*\.[0-9]*\.[0-9]* /soft_ver:1.0.0 /g' /etc/partition_config/soft-version")
            driver.web_upgrade(upfile)
            time.sleep(5)
            if (cur_version[:4] != version[:4]):
                driver.serial_send("nvrammanager -e -p user-config") # 跨大版本降级时清配置防止意外Bug

            # 等待设备启动
            time.sleep(120)
            driver.serial_login(setting["serial_passwd"])
            driver.serial_send("cat /etc/partition_config/soft-version")
            if not driver.serial_find(version ,duration=2):
                raise RuntimeError("降级失败")
            device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
            driver.web_login(device_ip, passwd=setting["passwd"])
            driver.web_skip_qs()

            # 升级到提测版本
            if not driver.web_upgrade(upfile_list["current_version"][1]):
                raise RuntimeError("升级到目标版本失败")
            time.sleep(120)
            i = 30
            while i>0 and not driver.ping(device_ip):
                i -= 1
                
            driver.serial_login(setting["serial_passwd"])
            driver.serial_send("cat /etc/partition_config/soft-version")
            if not driver.serial_find(cur_version ,duration=2):
                raise RuntimeError("升级到目标版本失败")
            device_ip = driver.serial_getip() or setting.get("device_ip", "192.168.0.1")
            driver.web_login(device_ip, passwd=setting["passwd"])
            driver.web_skip_qs()
            driver.web_page("firmware")
            if cur_version == parse_version(driver.find("Firmware Version",["right"]).text()):
                result[result_str] = True
            driver.assert_custom(result[result_str], "", msg=f"版本{version}旧升新")
        driver.serial_send("rm /tp_data/product-info; mv /etc/partition_config/product-info_bk /tp_data/product-info")

except Exception as e:
    log(e) and print(f"测试执行过程中发生异常")

finally:
    driver.assert_custom(result and all(result.values()), result, msg="脚本执行结果")
    driver.quit()

