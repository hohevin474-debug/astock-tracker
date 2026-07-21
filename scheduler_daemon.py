#!/usr/bin/env python3
"""
A股短线跟踪 — 24/7 定时调度守护进程 v2
直接在本地 sandbox 运行，输出到 WorkBuddy 聊天框 + Bark 推送
"""
import sys
import os
import time
import logging
import subprocess
from datetime import datetime, timedelta

sys.path.insert(0, '/workspace/stock-tracker')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/workspace/stock-tracker/scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('scheduler')

# 推送时间表（北京时间）
SCHEDULE = [
    ("09:00", "pre_market"),
    ("10:30", "intraday_1"),
    ("11:30", "midday"),
    ("14:00", "intraday_3"),
    ("15:00", "close"),
]

sent_today = {}


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


def is_trading_day(d):
    return d.weekday() < 5


def trigger_local(mode: str):
    """直接在本地运行报告生成"""
    logger.info(f"🚀 本地运行: {mode}")
    try:
        result = subprocess.run(
            ['python3', 'main.py', mode],
            cwd='/workspace/stock-tracker',
            capture_output=True,
            text=True,
            timeout=120
        )
        # 输出到 stdout（会显示在 WorkBuddy 聊天框）
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            # 过滤掉字体警告
            for line in result.stderr.split('\n'):
                if 'notdef glyph' not in line and line.strip():
                    print(f"[!] {line}", file=sys.stderr)
        
        if result.returncode == 0:
            logger.info(f"✅ {mode} 执行成功")
            return True
        else:
            logger.error(f"❌ {mode} 执行失败 (exit code: {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"⏰ {mode} 执行超时")
        return False
    except Exception as e:
        logger.error(f"❌ {mode} 执行异常: {e}")
        return False


def check_and_trigger():
    global sent_today
    
    now = beijing_now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    
    # 新的一天重置
    if sent_today.get("date") != today_str:
        sent_today = {"date": today_str}
        logger.info(f"📅 新的一天: {today_str} (周{['一','二','三','四','五','六','日'][now.weekday()]})")
    
    # 非交易日跳过
    if not is_trading_day(now):
        return
    
    # 检查每个时间点
    for schedule_time, mode in SCHEDULE:
        if time_str == schedule_time and mode not in sent_today:
            logger.info(f"⏰ 到达推送时间: {schedule_time} → {mode}")
            success = trigger_local(mode)
            if success:
                sent_today[mode] = time_str
                logger.info(f"✅ {mode} 已完成")
            else:
                logger.warning(f"⚠️ {mode} 失败，下次循环重试")
            return


def run():
    logger.info("=" * 50)
    logger.info("🟢 A股短线跟踪 · 调度守护进程 v2 启动")
    logger.info("   模式: 本地直接运行（输出到 WorkBuddy 聊天框）")
    logger.info(f"   推送时间: {', '.join(t for t,_ in SCHEDULE)}")
    logger.info("   检查间隔: 30 秒")
    logger.info("=" * 50)
    
    while True:
        try:
            check_and_trigger()
        except Exception as e:
            logger.error(f"调度异常: {e}")
        
        time.sleep(30)


if __name__ == "__main__":
    run()
