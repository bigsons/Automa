# 加载 IxChariot 包
load ChariotExt
package require ChariotExt

# 创建测试对象
set test [chrTest new]
set runOpts [chrTest getRunOpts $test]
chrRunOpts set $runOpts TEST_END FIXED_DURATION
chrRunOpts set $runOpts TEST_DURATION 30 ;# 设置测试时长为30秒

# 创建 Pair 对象
set pair [chrPair new]
chrPair set $pair E1_ADDR "192.168.137.1" E2_ADDR "192.168.137.101"
chrPair set $pair PROTOCOL TCP

# 设置测试脚本
chrPair useScript $pair "C:/Users/admin/Desktop/Throughput.scr"
# 添加 Pair 到测试对象中
chrTest addPair $test $pair

# 启动测试
chrTest start $test

# 等待测试完成并读取结果
if {![chrTest isStopped $test 40]} {
puts "ERROR: Test didn’t stop"
chrTest delete $test force
return
}
set throughput [chrPairResults get $pair THROUGHPUT]
puts "Throughput: [lindex $throughput 0] Mbps"

# 保存测试结果并清理
chrTest save $test "C:/Users/admin/Desktop/test_result.tst"
chrTest delete $test force