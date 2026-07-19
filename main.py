#!/usr/bin/env python3
"""
A股短线跟踪系统 — 主调度器
统一入口，根据运行模式生成对应报告并通过 Bark 推送到手机

用法:
  python main.py pre_market     # 盘前推送（9:00）
  python main.py intraday_1     # 盘中更新#1（10:30）
  python main.py midday         # 午间更新（11:30）
  python main.py intraday_3     # 盘中更新#3（14:00）
  python main.py close          # 收盘总结（15:00）
  python main.py test           # 测试模式（立即运行盘前报告）
  python main.py setup_bark     # 配置 Bark 推送
  python main.py status         # 系统状态
"""
import sys
import os
import logging
import yaml
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

from market_data import (
    get_realtime_quotes, get_market_index, get_sector_flow,
    get_limit_up_down_stats, get_dragon_tiger_board, is_trading_day
)
from stock_screener import generate_weekly_pool, update_pool_prices, get_sector_hotness
from report_generator import (
    generate_pre_market_report, generate_intraday_update, generate_plain_text_report
)
from push_sender import (
    save_report, send_bark, build_push_summary, get_device_key, save_device_key
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)


def get_recipient_email() -> str:
    """获取收件人邮箱"""
    if os.path.exists(RECIPIENT_EMAIL_FILE):
        with open(RECIPIENT_EMAIL_FILE, 'r') as f:
            return f.read().strip()
    return ''


def save_recipient_email(email: str):
    """保存收件人邮箱"""
    with open(RECIPIENT_EMAIL_FILE, 'w') as f:
        f.write(email.strip())


def _push_to_bark(pool: list, indices: dict, report_type: str, html: str):
    """统一推送逻辑：Bark 通知 + 本地保存"""
    # 1. 保存 HTML 报告到本地
    filepath = save_report(html, report_type)
    
    # 2. Bark 推送摘要
    device_key = get_device_key()
    if device_key:
        title, body = build_push_summary(pool, indices, report_type)
        success = send_bark(title, body, group="A股短线跟踪")
        logger.info(f"Bark 推送: {'✅ 成功' if success else '❌ 失败'}")
    else:
        logger.warning("未配置 Bark Device Key，跳过手机推送")
    
    return filepath


def run_pre_market():
    """盘前推送：选股 + 买卖价格 + 隔夜资讯"""
    logger.info("="*60)
    logger.info("执行盘前推送任务")
    logger.info("="*60)
    
    # 检查是否为交易日
    if not is_trading_day():
        logger.info("今天非交易日，跳过盘前推送")
        return
    
    # 生成/更新精选池（周一强制刷新）
    today = datetime.now()
    force_refresh = today.weekday() == 0  # 周一刷新
    pool = generate_weekly_pool(force_refresh=force_refresh)
    
    if not pool:
        logger.error("精选池为空，无法生成报告")
        return
    
    # 获取市场数据
    indices = get_market_index()
    hot_sectors = get_sector_hotness()
    limit_up_stats = get_limit_up_down_stats()
    
    # 生成报告
    html = generate_pre_market_report(pool, indices, hot_sectors, limit_up_stats)
    plain = generate_plain_text_report(pool, indices, 'pre_market')
    
    # 推送
    _push_to_bark(pool, indices, 'pre_market', html)
    
    logger.info("盘前推送完成")


def run_intraday_update(update_type: str):
    """盘中更新"""
    logger.info("="*60)
    logger.info(f"执行盘中更新: {update_type}")
    logger.info("="*60)
    
    if not is_trading_day():
        logger.info("今天非交易日，跳过盘中更新")
        return
    
    # 加载精选池
    pool = generate_weekly_pool(force_refresh=False)
    
    if not pool:
        logger.error("精选池为空")
        return
    
    # 更新实时价格
    pool = update_pool_prices(pool)
    
    # 获取市场数据
    indices = get_market_index()
    hot_sectors = get_sector_hotness()
    
    # 生成报告
    html = generate_intraday_update(pool, indices, hot_sectors, update_type)
    plain = generate_plain_text_report(pool, indices, update_type)
    
    # 推送
    _push_to_bark(pool, indices, update_type, html)
    
    logger.info(f"盘中更新 {update_type} 完成")


def run_test():
    """测试模式：立即运行盘前报告（跳过交易日检查）"""
    logger.info("测试模式：生成盘前报告（强制运行，跳过交易日检查）...")
    
    # 强制刷新精选池
    pool = generate_weekly_pool(force_refresh=True)
    
    if not pool:
        logger.error("精选池为空，无法生成报告")
        return
    
    # 获取市场数据
    indices = get_market_index()
    hot_sectors = get_sector_hotness()
    limit_up_stats = get_limit_up_down_stats()
    
    # 生成报告
    html = generate_pre_market_report(pool, indices, hot_sectors, limit_up_stats)
    plain = generate_plain_text_report(pool, indices, 'pre_market')
    
    # 推送
    filepath = _push_to_bark(pool, indices, 'pre_market', html)
    print(f"\n✅ 测试报告已生成: {filepath}")
    print(f"📊 报告中心: {os.path.join(PROJECT_DIR, 'public', 'index.html')}")
    
    # Bark 状态
    key = get_device_key()
    if key:
        print(f"📱 Bark 推送: {'已配置' if key else '未配置'} (Device Key: {key[:8]}...)")
    else:
        print("📱 Bark 未配置，运行 python3 main.py setup_bark 配置")
    
    logger.info("测试完成")


def setup_bark():
    """配置 Bark 推送"""
    print("\n" + "="*50)
    print("📱 A股短线跟踪系统 — Bark 推送配置")
    print("="*50)
    print()
    print("Bark 是一款 iOS 推送 App，可以将消息推送到你的 iPhone。")
    print()
    print("配置步骤：")
    print("1. 在 App Store 下载 Bark")
    print("2. 打开 App，首页会显示一个 Device Key（长按复制）")
    print("3. 将 Device Key 粘贴到下方")
    print()
    
    key = input("请输入 Bark Device Key: ").strip()
    
    if not key:
        print("❌ Device Key 不能为空")
        return
    
    save_device_key(key)
    print(f"\n✅ Device Key 已保存")
    
    # 发送测试推送
    print("\n发送测试推送...")
    success = send_bark(
        "🧪 Bark 推送测试",
        "A股短线跟踪系统已就绪！\n\n你将在每个交易日收到：\n• 09:00 盘前精选池\n• 10:30/11:30/14:00 盘中更新\n• 15:00 收盘总结\n\n⚠️ 本报告仅供参考，不构成投资建议。",
        group="A股短线跟踪",
        sound="birdsong"
    )
    
    if success:
        print("✅ 测试推送已发送！请检查你的 iPhone 通知。")
    else:
        print("⚠️ 推送发送失败，请检查：")
        print("   1. Device Key 是否正确")
        print("   2. iPhone 是否已安装并打开 Bark")
        print("   3. 网络是否正常")
    
    print("\n" + "="*50)
    print("Bark 配置完成！")
    print("="*50)


def show_status():
    """显示系统状态"""
    print("\n" + "="*50)
    print("📊 A股短线跟踪系统 — 状态")
    print("="*50)
    
    # Bark 状态
    key = get_device_key()
    if key:
        print(f"✅ Bark 推送: 已配置 (Device Key: {key[:8]}...)")
    else:
        print("❌ Bark 未配置，请运行: python3 main.py setup_bark")
    
    # 精选池缓存
    cache_file = os.path.join(os.path.dirname(__file__), '.pool_cache.json')
    if os.path.exists(cache_file):
        import json
        with open(cache_file, 'r') as f:
            cache = json.load(f)
        print(f"✅ 精选池缓存: {cache.get('week', 'N/A')} | {len(cache.get('pool', []))}只标的")
        print(f"   更新时间: {cache.get('generated_at', 'N/A')}")
    else:
        print("❌ 暂无精选池缓存")
    
    # 报告数量
    reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
    if os.path.exists(reports_dir):
        count = len([f for f in os.listdir(reports_dir) if f.endswith('.html')])
        print(f"📁 本地报告: {count} 份")
    else:
        print("📁 暂无本地报告")
    
    # 交易状态
    print(f"\n📅 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 是否交易日: {'是' if is_trading_day() else '否'}")
    
    print("="*50)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print("  python main.py pre_market    # 盘前推送")
        print("  python main.py intraday_1    # 盘中更新#1 (10:30)")
        print("  python main.py midday        # 午间更新 (11:30)")
        print("  python main.py intraday_3    # 盘中更新#3 (14:00)")
        print("  python main.py close         # 收盘总结 (15:00)")
        print("  python main.py test          # 测试模式")
        print("  python main.py setup_bark    # 配置 Bark 推送")
        print("  python main.py status        # 系统状态")
        sys.exit(1)
    
    mode = sys.argv[1]
    
    if mode == 'pre_market':
        run_pre_market()
    elif mode == 'intraday_1':
        run_intraday_update('intraday_1')
    elif mode == 'midday':
        run_intraday_update('midday')
    elif mode == 'intraday_3':
        run_intraday_update('intraday_3')
    elif mode == 'close':
        run_intraday_update('close')
    elif mode == 'test':
        run_test()
    elif mode == 'setup_bark':
        setup_bark()
    elif mode == 'status':
        show_status()
    else:
        print(f"未知模式: {mode}")
        print("可用模式: pre_market, intraday_1, midday, intraday_3, close, test, setup_bark, status")
        sys.exit(1)
