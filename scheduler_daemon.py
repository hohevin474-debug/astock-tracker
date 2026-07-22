#!/usr/bin/env python3
"""
A股短线跟踪 — 24/7 调度守护进程 v4
直接调用 main.py 生成报告，通过 wb-issues API 自动推送消息到项目
"""
import sys
import os
import time
import logging
import subprocess
import json
import urllib.request
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

SCHEDULE = [
    ("09:00", ["pre_market", "track"]),
    ("10:30", ["intraday_1", "track"]),
    ("11:30", ["midday", "track"]),
    ("14:00", ["intraday_3", "track"]),
    ("15:00", ["close", "track"]),
]

sent_today = {}

# wb-issues MCP endpoint
WB_ISSUES_URL = os.environ.get('WB_ISSUES_URL', 'http://localhost:3000')


def beijing_now():
    return datetime.utcnow() + timedelta(hours=8)


def is_trading_day(d):
    return d.weekday() < 5


def send_project_message(content: str):
    """通过 wb-issues API 发送项目消息（自动显示在聊天框）"""
    try:
        payload = json.dumps({
            "content": content,
        }).encode('utf-8')
        req = urllib.request.Request(
            f"{WB_ISSUES_URL}/api/project/messages",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10)
        logger.info(f"📨 项目消息已发送 (HTTP {resp.status})")
        return True
    except Exception as e:
        logger.warning(f"wb-issues 消息发送失败（将用文件兜底）: {e}")
        return False


def trigger_and_notify(modes: list):
    """运行报告并发送消息"""
    all_outputs = []
    
    for mode in modes:
        logger.info(f"🚀 {mode}")
        try:
            result = subprocess.run(
                ['python3', 'main.py', mode],
                cwd='/workspace/stock-tracker',
                capture_output=True,
                text=True,
                timeout=120
            )
            output = result.stdout
            if result.returncode != 0:
                output += f"\n❌ 错误: {result.stderr[:300]}"
            all_outputs.append(output)
            logger.info(f"✅ {mode} 完成")
        except subprocess.TimeoutExpired:
            logger.error(f"⏰ {mode} 超时")
            all_outputs.append(f"⏰ {mode} 执行超时")
        except Exception as e:
            logger.error(f"❌ {mode}: {e}")
            all_outputs.append(f"❌ {mode}: {e}")
        time.sleep(2)
    
    # 合并输出，只取文本摘要部分（从 "===" 开始到 "PDF 报告" 结束）
    combined = ""
    for i, output in enumerate(all_outputs):
        lines = output.split('\n')
        # 找到报告内容区域
        in_report = False
        report_lines = []
        for line in lines:
            if line.startswith('===') and '='*20 in line:
                in_report = True
            if in_report:
                if line.startswith('2026') and '[INFO]' in line:
                    continue
                report_lines.append(line)
        
        if i > 0:
            combined += "\n" + "─" * 40 + "\n\n"
        combined += '\n'.join(report_lines)
    
    if combined.strip():
        # 加标题
        now = beijing_now()
        weekday = ['一','二','三','四','五','六','日'][now.weekday()]
        header = f"## 📊 A股推送 · 周{weekday} {now.strftime('%H:%M')}\n\n"
        
        # 截断过长内容
        if len(combined) > 3000:
            combined = combined[:3000] + "\n\n... (内容过长已截断，完整报告见 PDF)"
        
        full_msg = header + combined + "\n\n> ⚠️ 仅供参考，不构成投资建议"
        
        # 发送到项目
        success = send_project_message(full_msg)
        
        # 兜底：写入文件
        push_file = '/workspace/stock-tracker/.last_push.txt'
        with open(push_file, 'w') as f:
            f.write(full_msg)
        
        return success
    
    return False


def check_and_trigger():
    global sent_today
    
    now = beijing_now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    
    if sent_today.get("date") != today_str:
        sent_today = {"date": today_str}
        logger.info(f"📅 新的一天: {today_str}")
    
    if not is_trading_day(now):
        return
    
    for schedule_time, modes in SCHEDULE:
        if time_str == schedule_time and schedule_time not in sent_today:
            logger.info(f"⏰ {schedule_time} → {modes}")
            success = trigger_and_notify(modes)
            if success:
                sent_today[schedule_time] = time_str
                logger.info(f"✅ {schedule_time} 推送+通知完成")
            else:
                logger.warning(f"⚠️ {schedule_time} 消息发送失败，已保存到文件")
                sent_today[schedule_time] = time_str  # 不重试
            return


def run():
    logger.info("=" * 50)
    logger.info("🟢 守护进程 v4 启动（自动推送消息到聊天框）")
    logger.info(f"   推送: {', '.join(t for t,_ in SCHEDULE)}")
    logger.info("=" * 50)
    
    while True:
        try:
            check_and_trigger()
        except Exception as e:
            logger.error(f"异常: {e}")
        time.sleep(30)


if __name__ == "__main__":
    run()
