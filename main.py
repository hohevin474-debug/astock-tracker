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
  python main.py track          # 持仓跟踪分析
  python main.py test           # 测试模式（立即运行盘前报告）
  python main.py setup_bark     # 配置 Bark 推送
  python main.py status         # 系统状态
"""
import sys
import os
import json
import logging
import yaml
from datetime import datetime, timedelta

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
from position_tracker import (
    track_all_positions, build_track_summary, build_daily_analysis,
    load_positions
)
from pdf_generator import generate_pdf, build_text_summary

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

# ====== 推送时间窗口（北京时间） ======
# 每个推送在时间窗口内只发一次（防重复）
# 窗口 20 分钟确保 GitHub Actions 每 15 分钟 cron 至少有 1 次机会命中
PUSH_SLOTS = {
    'pre_market':  {'hour': 9,  'minute': 0,  'window': 20},  # 09:00-09:20
    'intraday_1':  {'hour': 10, 'minute': 30, 'window': 20},  # 10:30-10:50
    'midday':      {'hour': 11, 'minute': 30, 'window': 20},  # 11:30-11:50
    'intraday_3':  {'hour': 14, 'minute': 0,  'window': 20},  # 14:00-14:20
    'close':       {'hour': 15, 'minute': 0,  'window': 20},  # 15:00-15:20
}

# 防重复文件路径（每个 workflow run 独立，用 .sent 文件记录当天已发推送）
SENT_FILE = os.path.join(PROJECT_DIR, '.sent_today.json')


def _get_beijing_time() -> datetime:
    """获取当前北京时间"""
    return datetime.utcnow() + timedelta(hours=8)


def _should_push(slot_name: str) -> bool:
    """
    判断当前时间是否在指定推送的时间窗口内，且今天尚未发送过。
    返回 True 表示应该执行推送。
    """
    if slot_name not in PUSH_SLOTS:
        return False
    
    slot = PUSH_SLOTS[slot_name]
    now = _get_beijing_time()
    today_str = now.strftime('%Y-%m-%d')
    
    # 检查是否在时间窗口内
    slot_time = now.replace(hour=slot['hour'], minute=slot['minute'], second=0, microsecond=0)
    window_end = slot_time + timedelta(minutes=slot['window'])
    
    if now < slot_time or now >= window_end:
        return False
    
    # 检查今天是否已经发送过
    sent = _load_sent_records()
    if sent.get('date') != today_str:
        # 新的一天，重置记录
        sent = {'date': today_str, 'slots': {}}
        _save_sent_records(sent)
    
    if slot_name in sent.get('slots', {}):
        logger.info(f"⏭ {slot_name} 今天已推送过，跳过")
        return False
    
    return True


def _mark_sent(slot_name: str):
    """标记某个时间槽已发送"""
    sent = _load_sent_records()
    today_str = _get_beijing_time().strftime('%Y-%m-%d')
    if sent.get('date') != today_str:
        sent = {'date': today_str, 'slots': {}}
    sent.setdefault('slots', {})[slot_name] = _get_beijing_time().isoformat()
    _save_sent_records(sent)


def _load_sent_records() -> dict:
    """加载已发送记录"""
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_sent_records(records: dict):
    """保存已发送记录"""
    try:
        with open(SENT_FILE, 'w') as f:
            json.dump(records, f)
    except IOError as e:
        logger.warning(f"无法保存发送记录: {e}")


def run_auto():
    """
    智能自动模式：
    - 根据北京时间自动判断应该执行哪个推送
    - 通过 .sent_today.json 防重复（每个推送每天只发一次）
    - 只在交易日运行
    """
    now = _get_beijing_time()
    logger.info(f"🤖 Auto 模式启动 | 北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')} (周{['一','二','三','四','五','六','日'][now.weekday()]})")
    
    if not is_trading_day():
        logger.info("今天非交易日，跳过所有推送")
        return
    
    # 按优先级检查各个推送槽位
    triggered = None
    for slot_name in ['pre_market', 'intraday_1', 'midday', 'intraday_3', 'close']:
        if _should_push(slot_name):
            triggered = slot_name
            break
    
    if not triggered:
        # 检查是否在周末测试模式
        now_str = now.strftime('%H:%M')
        logger.info(f"⏰ 当前时间 {now_str} 不在任何推送窗口内，跳过")
        return
    
    logger.info(f"🎯 触发推送: {triggered}")
    
    # 执行对应的推送
    if triggered == 'pre_market':
        run_pre_market()
    elif triggered in ('intraday_1', 'midday', 'intraday_3', 'close'):
        run_intraday_update(triggered)
    
    # 标记已发送
    _mark_sent(triggered)
    logger.info(f"✅ {triggered} 推送完成，已标记")


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
    """统一推送逻辑：Bark 通知 + PDF 生成 + WorkBuddy 聊天框展示"""
    # 1. 保存 HTML 报告到本地
    filepath = save_report(html, report_type)
    
    # 2. 生成 PDF
    pdf_path = generate_pdf(html, report_type, pool, indices)
    
    # 3. 生成文本摘要（用于 WorkBuddy 聊天框）
    text_summary = build_text_summary(pool, indices, report_type)
    
    # 4. Bark 推送摘要
    device_key = get_device_key()
    if device_key:
        title, body = build_push_summary(pool, indices, report_type)
        success = send_bark(title, body, group="A股短线跟踪")
        logger.info(f"Bark 推送: {'✅ 成功' if success else '❌ 失败'}")
    else:
        logger.warning("未配置 Bark Device Key，跳过手机推送")
    
    # 5. 输出到 WorkBuddy 聊天框
    print("\n" + text_summary)
    if pdf_path:
        print(f"\n📄 PDF 报告: {pdf_path}")
    
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
    
    # ====== 持仓跟踪（14:00和15:00附带深度分析） ======
    if update_type in ('intraday_3', 'close'):
        _run_track_analysis(pool, update_type)
    
    logger.info(f"盘中更新 {update_type} 完成")


def run_track():
    """独立持仓跟踪分析"""
    logger.info("="*60)
    logger.info("执行持仓跟踪分析")
    logger.info("="*60)
    
    pool = generate_weekly_pool(force_refresh=False)
    if not pool:
        pool = generate_weekly_pool(force_refresh=True)
    
    _run_track_analysis(pool, 'track')


def _run_track_analysis(pool: list, mode: str):
    """持仓跟踪核心逻辑"""
    logger.info("分析持仓状态...")
    
    # 更新池内价格
    pool = update_pool_prices(pool)
    
    # 跟踪所有持仓
    result = track_all_positions(pool)
    
    # 发送持仓摘要推送
    summary_text = build_track_summary(result)
    send_bark(
        f"📊 持仓跟踪 · {datetime.now().strftime('%H:%M')}",
        summary_text,
        group="A股持仓跟踪"
    )
    
    # WorkBuddy 聊天框输出
    print("\n" + summary_text)
    
    # 如果有卖出/减仓警报，单独推送
    for alert in result['alerts']:
        if alert['type'] in ('卖出', '减仓'):
            send_bark(alert['title'], alert['body'], group="A股持仓跟踪", sound="alarm")
            print(f"\n🚨 {alert['title']}: {alert['body']}")
    
    # 14:00 和收盘时发送深度分析
    if mode in ('intraday_3', 'close', 'track'):
        analysis = build_daily_analysis(result['active'])
        if analysis:
            send_bark(
                f"🔍 深度分析 · {datetime.now().strftime('%H:%M')}",
                analysis[:500],
                group="A股持仓跟踪"
            )
            print(f"\n🔍 深度分析:\n{analysis[:1000]}")
    
    logger.info(f"持仓跟踪完成: {result['summary']['total']}只活跃, {len(result['alerts'])}条警报")


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
        print("  python main.py track         # 持仓跟踪分析")
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
    elif mode == 'track':
        run_track()
    elif mode == 'test':
        run_test()
    elif mode == 'setup_bark':
        setup_bark()
    elif mode == 'status':
        show_status()
    elif mode == 'auto':
        run_auto()
    else:
        print(f"未知模式: {mode}")
        print("可用模式: pre_market, intraday_1, midday, intraday_3, close, track, test, setup_bark, status, auto")
        sys.exit(1)
