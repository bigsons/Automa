# -*- coding: utf-8 -*-

import time
import inspect
import functools
import traceback
import airtest.core.helper
from airtest.core.error import LocalDeviceError

def patch_airtest_logwrap():
    """
    用自定义的 Logwrap 函数替换 airtest.core.helper 中的 logwrap，
    以增加对 G.LOGGER._extra_log_data 的处理。
    """
    from airtest.core.helper import G

    def custom_Logwrap(f, logger):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            from airtest.core.cv import try_log_screen
            depth = kwargs.pop('depth', None)
            start = time.time()
            m = inspect.getcallargs(f, *args, **kwargs)
            snapshot = m.pop('snapshot', False)
            m.pop('self', None)
            m.pop('cls', None)
            fndata = {'name': f.__name__, 'call_args': m, 'start_time': start}
            logger.running_stack.append(fndata)
            
            try:
                res = f(*args, **kwargs)
            except LocalDeviceError:
                raise LocalDeviceError
            except Exception as e:
                data = {"traceback": traceback.format_exc(), "end_time": time.time()}
                fndata.update(data)
                raise
            else:
                # ============================================================
                # 检查"信箱" G.LOGGER._extra_traceback_data 自定义的识别log是否存在
                if hasattr(G.LOGGER, "_extra_traceback_data"):
                    fndata.update(G.LOGGER._extra_traceback_data)
                    del G.LOGGER._extra_traceback_data
                # ============================================================
                fndata.update({'ret': res, "end_time": time.time()})
                return res
            finally:
                if snapshot is True:
                    try:
                        try_log_screen(depth=len(logger.running_stack) + 1)
                    except AttributeError:
                        pass
                
                # ============================================================
                # 检查"信箱" G.LOGGER._extra_log_data 是否存在
                if hasattr(G.LOGGER, "_extra_log_data"):
                    fndata.update(G.LOGGER._extra_log_data)
                    del G.LOGGER._extra_log_data
                # ============================================================
                    
                logger.log('function', fndata, depth=depth)
                try:
                    logger.running_stack.pop()
                except IndexError:
                    pass
        return wrapper

    new_logwrap = lambda f: custom_Logwrap(f, G.LOGGER)
    airtest.core.helper.logwrap = new_logwrap

# 当本模块被导入时，立即执行补丁操作
patch_airtest_logwrap()