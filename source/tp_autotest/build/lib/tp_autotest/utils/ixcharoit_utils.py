import os, sys, time, re


class km:
    def __init__(self, rootdir="./"):
        self.script = os.path.join(rootdir, "Script", "Throughput.scr").replace("\\", "/")
        self.downscript = os.path.join(rootdir, "Script", "Throughputdown.scr").replace("\\", "/")
        self.chariot_result = rootdir + "result"
        self.tcl_code = None

    def save_chariot(self, allstr=None):
        fd = open(self.chariot_result, "a+")
        fd.write(allstr + "\n")
        fd.close()

    def generate_tcl_script(self, **kargs):
        self.start_ip = kargs["sip"].split(" ")
        self.sip_len = len(self.start_ip)
        self.dst_ip = kargs["dip"].split(" ")
        self.dip_len = len(self.dst_ip)
        self.tx_pair = kargs["tx_pair"]
        self.rx_pair = kargs["rx_pair"]
        self.sum_pair = self.tx_pair + self.rx_pair
        self.proto = kargs["proto"].upper()
        self.run_time = kargs["run_time"]

        self.tcl_code.append("load ChariotExt")
        self.tcl_code.append("package require ChariotExt")

        if not "name" in kargs.keys():
            test_result = os.gettime() + ".tst"
        else:
            test_result = kargs["name"] + "_" + os.gettime() + ".tst"
        test_now = os.path.join("./result", test_result).replace("\\", "/")
        print("test_now=", test_now)
        # 创建test
        self.tcl_code.append("set test [chrTest new]")
        # 设置运行时间
        self.tcl_code.append("set runOpts [chrTest getRunOpts $test]")
        self.tcl_code.append("chrRunOpts set $runOpts TEST_END FIXED_DURATION")
        self.tcl_code.append("chrRunOpts set $runOpts TEST_DURATION %d" % (self.run_time))
        # 向test中添加pair

        for i in range(0, self.sum_pair):
            self.tcl_code.append("set pair%d [chrPair new]" % i)
            self.tcl_code.append("chrPair set [set pair%d] PROTOCOL %s" % (i, self.proto.upper()))
            self.tcl_code.append("chrPair set [set pair%d] E1_ADDR %s" % (i, self.start_ip[i % self.sip_len]))
            self.tcl_code.append("chrPair set [set pair%d] E2_ADDR %s" % (i, self.dst_ip[i % self.dip_len]))
            if i < self.tx_pair:
                self.tcl_code.append('chrPair useScript [set pair%d] "%s" ' % (i, self.script))
            else:
                self.tcl_code.append('chrPair useScript [set pair%d] "%s" ' % (i, self.downscript))
            self.tcl_code.append("chrTest addPair $test [set pair%d]" % (i))
        self.tcl_code.append("chrTest start $test")
        time.sleep(2)
        if self.run_time < 10:
            chktime = 60
        else:
            chktime = 3 * self.run_time
        for j in range(0, chktime):
            ret = self.tcl_code.append("chrTest isStopped $test")
            print("ret=", ret)
            print("j=%d total=%d" % (j, chktime))
            time.sleep(1)
            if ret == "1":
                print("chariot run done")
                break
            else:
                time.sleep(2)
            if j > self.run_time:
                try:
                    self.tcl_code.append("chrTest stop $test")
                except Exception as e:
                    print(str(e))
        # 获取测试结果
        max_runtime = 1
        errnum = 0
        sum_throught = 0.0
        for j in range(0, self.sum_pair):
            try:
                run_pair_time = self.tcl_code.append("set runingtime [chrCommonResults get [set pair%d] MEAS_TIME]" % (j))
                # print("run_pair_time=",run_pair_time
                run_pair_time = float(run_pair_time)
                if run_pair_time > max_runtime:
                    max_runtime = run_pair_time
                throuput_pair = self.tcl_code.append("set throughput [chrPairResults get [set pair%d] THROUGHPUT]" % (j))
                avg_throuput = throuput_pair.split(" ")[0]
                sum_throught = sum_throught + float(avg_throuput) * run_pair_time
            except Exception as e:
                errnum = errnum + 1
                print(str(e))
        print("sum_throught=", sum_throught)
        print("max_runtime=", max_runtime)
        if self.run_time - max_runtime <= 1:
            max_runtime = float(self.run_time)

        ret = sum_throught / max_runtime
        # print(u"平均吞吐量为%.3f" %(sum_throught/max_runtime)
        self.tcl_code.append('chrTest save $test "%s"' % (test_now))
        self.tcl_code.append("chrTest delete $test force")



if __name__ == "__main__":
    km_obj = km()
    kargs = {
        "sip": "127.0.0.1 127.0.0.1",
        "dip": "127.0.0.1 127.0.0.1",
        "sum_pair": 20,
        "tx_pair": 20,
        "proto": "TCP",
        "run_time": 10,
    }
    km_obj.run_Ixchariot(**kargs)
