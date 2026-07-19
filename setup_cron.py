#!/usr/bin/env python3
"""
A股短线跟踪系统 — 定时任务配置
通过 automation-task-manager 的 scheduler API 创建 Cron 任务
"""
import os
import sys
import json
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 项目目录
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Scheduler API 脚本路径
SCHEDULER_SCRIPT = "/root/.codebuddy/skills/automation-task-manager/scripts/scheduler-api.sh"

# 定时任务配置
CRON_TASKS = [
    {
        'name': 'astock-pre-market',
        'description': 'A股盘前推送：选股+买卖价格+隔夜资讯（每个交易日9:00）',
        'cron': '0 0 9 * * 1-5',
        'frequency_type': 'daily',
        'prompt': f'请执行以下命令生成盘前报告: cd {PROJECT_DIR} && python3 main.py pre_market',
        'timezone': 'Asia/Shanghai',
    },
    {
        'name': 'astock-intraday-1',
        'description': 'A股盘中更新#1：开盘1小时走势（10:30）',
        'cron': '0 30 10 * * 1-5',
        'frequency_type': 'daily',
        'prompt': f'请执行以下命令生成盘中更新: cd {PROJECT_DIR} && python3 main.py intraday_1',
        'timezone': 'Asia/Shanghai',
    },
    {
        'name': 'astock-midday',
        'description': 'A股午间更新：半日复盘+午后展望（11:30）',
        'cron': '0 30 11 * * 1-5',
        'frequency_type': 'daily',
        'prompt': f'请执行以下命令生成午间报告: cd {PROJECT_DIR} && python3 main.py midday',
        'timezone': 'Asia/Shanghai',
    },
    {
        'name': 'astock-intraday-3',
        'description': 'A股盘中更新#3：午后走势+尾盘策略（14:00）',
        'cron': '0 0 14 * * 1-5',
        'frequency_type': 'daily',
        'prompt': f'请执行以下命令生成盘中更新: cd {PROJECT_DIR} && python3 main.py intraday_3',
        'timezone': 'Asia/Shanghai',
    },
    {
        'name': 'astock-close',
        'description': 'A股收盘总结：全天回顾+明日预判（15:00）',
        'cron': '0 0 15 * * 1-5',
        'frequency_type': 'daily',
        'prompt': f'请执行以下命令生成收盘总结: cd {PROJECT_DIR} && python3 main.py close',
        'timezone': 'Asia/Shanghai',
    },
]


def create_task(task_config: dict) -> bool:
    """创建单个定时任务"""
    name = task_config['name']
    
    # 先检查是否已存在
    logger.info(f"检查任务 {name} 是否存在...")
    list_result = subprocess.run(
        ['bash', SCHEDULER_SCRIPT, 'list', '--status', 'active'],
        capture_output=True, text=True
    )
    
    if name in list_result.stdout:
        logger.info(f"任务 {name} 已存在，跳过创建")
        return True
    
    # 创建任务
    logger.info(f"创建任务: {name}")
    cmd = [
        'bash', SCHEDULER_SCRIPT, 'create',
        '--name', name,
        '--cron', task_config['cron'],
        '--frequency-type', task_config['frequency_type'],
        '--prompt', task_config['prompt'],
        '--description', task_config['description'],
        '--timezone', task_config['timezone'],
        '--timeout', '600',
        '--retry-count', '3',
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        logger.info(f"创建结果: {result.stdout}")
        if result.returncode == 0:
            logger.info(f"✅ 任务 {name} 创建成功")
            return True
        else:
            logger.error(f"❌ 任务 {name} 创建失败: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"❌ 创建任务 {name} 异常: {e}")
        return False


def setup_all_tasks():
    """配置所有定时任务"""
    logger.info("="*60)
    logger.info("A股短线跟踪系统 — 定时任务配置")
    logger.info("="*60)
    
    if not os.path.exists(SCHEDULER_SCRIPT):
        logger.error(f"Scheduler API 脚本不存在: {SCHEDULER_SCRIPT}")
        logger.info("将使用备选方案：输出手动配置说明")
        print_manual_setup_guide()
        return
    
    success_count = 0
    for task in CRON_TASKS:
        if create_task(task):
            success_count += 1
    
    logger.info(f"\n配置完成: {success_count}/{len(CRON_TASKS)} 个任务创建成功")
    
    if success_count < len(CRON_TASKS):
        logger.warning("部分任务创建失败，请检查 scheduler API 状态")
        print_manual_setup_guide()


def print_manual_setup_guide():
    """打印手动配置指南"""
    print("\n" + "="*60)
    print("📋 手动配置定时任务指南")
    print("="*60)
    print()
    print("请使用以下 Cron 表达式配置定时任务：")
    print()
    for task in CRON_TASKS:
        print(f"  [{task['name']}]")
        print(f"    Cron: {task['cron']}")
        print(f"    说明: {task['description']}")
        print(f"    命令: cd {PROJECT_DIR} && python3 main.py {task['name'].replace('astock-', '')}")
        print()
    print("="*60)


def list_tasks():
    """列出所有已创建的定时任务"""
    if not os.path.exists(SCHEDULER_SCRIPT):
        print("Scheduler API 不可用")
        return
    
    result = subprocess.run(
        ['bash', SCHEDULER_SCRIPT, 'list'],
        capture_output=True, text=True
    )
    print(result.stdout)


def delete_all_tasks():
    """删除所有A股跟踪定时任务"""
    if not os.path.exists(SCHEDULER_SCRIPT):
        print("Scheduler API 不可用")
        return
    
    for task in CRON_TASKS:
        name = task['name']
        logger.info(f"删除任务: {name}")
        result = subprocess.run(
            ['bash', SCHEDULER_SCRIPT, 'delete', '--name', name],
            capture_output=True, text=True
        )
        print(f"  {name}: {result.stdout.strip()}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 setup_cron.py create    # 创建所有定时任务")
        print("  python3 setup_cron.py list      # 列出所有任务")
        print("  python3 setup_cron.py delete    # 删除所有A股任务")
        print("  python3 setup_cron.py manual    # 打印手动配置指南")
        sys.exit(1)
    
    action = sys.argv[1]
    
    if action == 'create':
        setup_all_tasks()
    elif action == 'list':
        list_tasks()
    elif action == 'delete':
        delete_all_tasks()
    elif action == 'manual':
        print_manual_setup_guide()
    else:
        print(f"未知操作: {action}")
