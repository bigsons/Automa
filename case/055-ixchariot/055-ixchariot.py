# -*- encoding=utf8 -*-
# ================================================================================ #
__author__ = "Your Name"
__brief__ = "Ixchariot 跑流脚本"
__desc__ = """脚本逻辑与测试步骤：
            0. 生成TCL脚本
            1. 用子进程运行，并获取结果"""
__req__ = []
# ================================================================================ #
import subprocess,sys
from utils.common import *
REQUIRED_RESOURCES_CHECK(__req__)

result = {}
end_point1 = "192.168.137.1"
end_point2 = "192.168.137.101"
pair_script = "c:/Program Files (x86)/Ixia/IxChariot/Scripts/Throughput.scr"
result_file = os.path.join(ST.LOG_DIR, "test_result.tst").replace('\\','/')

tcl_code = f""" # Generate IxCharoit tcl Script By Automa Tool
set e1 "{end_point1}"
set e2 "{end_point2}"
set script "{pair_script}"
set testFile "{result_file}"
set time 1

# (1)加载Chariot包
load ChariotExt
package require ChariotExt

# (2)创建测试对象
set test [chrTest new]
set runOpts [chrTest getRunOpts $test]
chrRunOpts set $runOpts TEST_END FIXED_DURATION
chrRunOpts set $runOpts TEST_DURATION $time; #设置测试运行时间

# (3)创建pair对象
set pair [chrPair new]

# (4)设置pair属性
chrPair set $pair E1_ADDR $e1 E2_ADDR $e2
chrPair set $pair PROTOCOL TCP; #设置协议
chrPair set $pair COMMENT  "TTESSTT"; #设置Comment

# (5)设置测试脚本
chrPair useScript $pair $script
# chrPair setScriptVar $pair file_size 1000000;#发送字节数
# chrPair setScriptVar $pair send_buffer_size 1500;#buffer大小
# chrPair setScriptVar $pair send_data_rate "20 Mb";#发送速率

# 创建组
set group1 [chrAppGroup new]
chrAppGroup set $group1 APP_GROUP_NAME "GROUP_UP" 
chrAppGroup addPair $group1 $pair 

# # (6)添加pair到测试对象中
chrTest addPair $test $pair

# # (6)添加组到测试对象中
# chrTest addAppGroup  $test $group1

# (7)运行测试
chrTest start $test

# (8)等待测试结束
set timeout [expr 10 + $time]
if {{![chrTest isStopped $test $timeout]}} {{
 puts "ERROR: Test didn't stop"
 chrTest delete $test force
 return
}}

# (9)打印
set throughput [chrPairResults get $pair THROUGHPUT]
set avg [format "%.3f" [lindex $throughput 0]]
set min [format "%.3f" [lindex $throughput 1]]
set max [format "%.3f" [lindex $throughput 2]]

# puts "E1 address: [chrPair get $pair E1_ADDR]"
# puts "E2 address: [chrPair get $pair E2_ADDR]"
# puts "Protocol: [chrPair get $pair PROTOCOL], Pairs: [chrTest getPairCount $test]"
# # We'll show both the script filename and the application script name.
# puts "Application : [chrPair get $pair APPL_SCRIPT_NAME]"
# puts "Script filename: [chrPair get $pair SCRIPT_FILENAME]"

puts ""
puts "Time record = [chrPair getTimingRecordCount $pair]"
puts "Throughput: avg = $avg, min = $min, max = $max"

# (11)保存测试结果
chrTest save $test $testFile
chrTest delete $test force

return
"""

try:
    tcl_path = os.path.join(ST.LOG_DIR,"tcl.tcl")
    with open(tcl_path, "w", encoding="utf-8") as f:
        f.write(tcl_code)
    command = ["tclkitsh", tcl_path]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    process.wait()


except Exception as e:
    log(e) and print(f"测试执行过程中发生异常{e}")

finally:
    log(process.stdout.read())
    log(process.stderr.read())


