import re
import json
from .webchrome import *

def REQUIRED_RESOURCES_CHECK(list):
    try:
        with open(ST.PROJECT_ROOT + "/setting.json", "r", encoding="utf-8") as f:
            setting = json.load(f)
            if not all(setting[item] for item in list):
                log(f"缺少执行所需资源，请在参数设置中配置{str(list)}")
                raise RuntimeError(f"\n\n缺少该脚本执行所需资源，请在UI的参数设置中配置, \n\n必选：{str(list)}")
    except FileNotFoundError:
        raise RuntimeError(f"工具配置文件损坏")

def parse_version(version_string):
    """
    从不同格式的字符串中解析版本号。

    Args:
        version_string: 包含版本信息的字符串

    Returns:
        匹配到的版本号形如1.0.0的字符串，如果未找到则返回 None
    """
    # 匹配 "be550v1-up-all-ver1-2-1-P1[20250813-rel27119]_nosign_2025-08-13_16.03.25.bin"
    match = re.search(r'ver(\d+-\d+-\d+)', version_string)
    if match:
        return match.group(1).replace('-', '.')
    
    # 匹配 "1.2.1 Build 20250813 rel.27119(5553)"
    match = re.search(r'(\d+\.\d+\.\d+)\s+Build', version_string)
    if match:
        return match.group(1)

    # 匹配 "v1.2.1" 或 "1.2.1"
    match = re.search(r'[vV]?(\d+\.\d+\.\d+)', version_string)
    if match:
        return match.group(1)

    return None

def parse_upfile(path, current_version):
    """
    分类包含 "up" 关键字的文件到不同版本类别中。

    Args:
        path (str): 要搜索的路径。
        current_version (str): 当前版本号（如 "1.0.0"）。

    Returns:
        包含分类结果的字典，键为版本类别，值为文件名列表。
        - "current_version": [],
        - "history_version": [],
        - "uptest_version": [],
    """
    result = {
        "current_version": [],
        "history_version": [],
        "uptest_version": [],
    }
    current_version = parse_version(current_version)
    if not path or not os.path.exists(path) or not current_version or current_version.count(".") != 2:
        return None
    
    current_parts = list(map(int, current_version.split(".")))
    for filename in os.listdir(path):
        if "-up-" in filename.lower() and "sign_" in filename.lower():  # 检查是否包含 "up" 关键字
            version = parse_version(filename)
            if not version or version.count(".") != 2:
                continue
            if version == current_version and "2048" in filename:
                result["current_version"].append(filename)
            elif version == current_version:
                result["current_version"].insert(0,filename)
            else:
                version_parts = list(map(int, version.split(".")))

                if version_parts < current_parts:
                    result["history_version"].append(filename)
                else:
                    result["uptest_version"].append(filename)

    # 对 history_version 降序排序
    result["history_version"].sort(
        key=lambda x: list(map(int,parse_version(x).split("."))),
        reverse=True,
    )
    # 对 uptest_version 升序排序
    result["uptest_version"].sort(
        key=lambda x: list(map(int,parse_version(x).split("."))),
    )

    return {k:[os.path.join(path,item) for item in v ] for k,v in result.items()}

if __name__ == '__main__':
    pass