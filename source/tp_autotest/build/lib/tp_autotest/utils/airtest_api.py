# -*- coding: utf-8 -*-

import time
import os
from airtest.core.helper import G, logwrap
from airtest import aircv
from airtest.aircv import get_resolution
from airtest.core.error import TargetNotFoundError
from airtest.core.settings import Settings as ST

@logwrap
def loop_find(query, driver=None, timeout=10, threshold=None, interval=0.5, intervalfunc=None):
    """
    Search for image template in the screen until timeout

    Args:
        query: image template to be found in screenshot
        timeout: time interval how long to look for the image template
        threshold: default is None
        interval: sleep interval before next attempt to find the image template
        intervalfunc: function that is executed after unsuccessful attempt to find the image template

    Raises:
        TargetNotFoundError: when image template is not found in screenshot

    Returns:
        TargetNotFoundError if image template not found, otherwise returns the position where the image template has
        been found in screenshot

    """
    start_time = time.time()
    while True:
        screen = driver.screenshot()
        query.resolution = get_resolution(screen)
        if screen is None:
            print("Screen is None, may be locked")
        else:
            if threshold:
                query.threshold = threshold
            match_pos = query.match_in(screen)
            if match_pos:
                try_log_screen(screen)
                return match_pos

        if intervalfunc is not None:
            intervalfunc()

        # 超时则raise，未超时则进行下次循环:
        if (time.time() - start_time) > timeout:
            try_log_screen(screen)
            raise TargetNotFoundError('Picture %s not found in screen' % query)
        else:
            time.sleep(interval)

@logwrap
def try_log_screen(screen=None, filename=None, pos=None):
    """
    Save screenshot to file

    Args:
        screen: screenshot to be saved

    Returns:
        None

    """
    if not ST.LOG_DIR:
        return
    if not filename:
        name = "%(time)d.jpg" % {'time': time.time() * 1000}
        filename = os.path.join(ST.LOG_DIR, name)
    if not os.path.isfile(filename):
        if screen is None:
            screen = G.DEVICE.snapshot()
        aircv.imwrite(filename, screen, 99)
    else:
        screen = aircv.imread(filename)
    return {"screen": filename, "resolution": aircv.get_resolution(screen),"pos": pos}

def save_screen(screen=None, filename=None, pos=None):
    if not filename:
        name = "%(time)d.jpg" % {'time': time.time() * 1000}
        filename = os.path.join(ST.LOG_DIR, name)
    if not os.path.isfile(filename):
        if screen is None:
            screen = G.DEVICE.snapshot()
        aircv.imwrite(filename, screen, 99)
    else:
        screen = aircv.imread(filename)
    return {"screen": filename, "resolution": aircv.get_resolution(screen),"pos": pos}

def set_step_log(log_content):
    """
    为一个被 @logwrap 装饰的步骤，在它的 log 'data' 中添加一个 'log' 字段。
    Args:
        log_content: 任何可以被JSON序列化的内容 (e.g., dict, list, string)。
    """
    if not hasattr(G.LOGGER, "_extra_log_data"):
        G.LOGGER._extra_log_data = {}
    
    # 将用户提供的内容存入 'log' 键中
    print(log_content)
    G.LOGGER._extra_log_data['log'] = log_content

def set_step_traceback(content):
    """
    为一个被 @logwrap 装饰的步骤，在它的 log 'data' 中添加一个 'traceback' 字段来自定义报告步骤执行失败
    Args:
        log_content: 任何可以被JSON序列化的内容 (e.g., dict, list, string)。
    """
    if not hasattr(G.LOGGER, "_extra_traceback_data"):
        G.LOGGER._extra_traceback_data = {}
    
    # 将用户提供的内容存入 'traceback' 键中
    print(content)
    G.LOGGER._extra_traceback_data['traceback'] = content
