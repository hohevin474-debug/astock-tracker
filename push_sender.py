"""
A股短线跟踪系统 — 推送模块
主推送：Bark（iOS 通知）→ 推送到手机
备用：本地HTML报告中心
"""
import os
import json
import logging
import yaml
import requests
import shutil
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), 'public')

BARK_CONFIG = CONFIG.get('bark', {})
BARK_SERVER = BARK_CONFIG.get('server', 'https://api.day.app')
BARK_KEY_FILE = os.path.join(os.path.dirname(__file__), '.bark_key')


def get_device_key() -> str:
    """获取 Bark Device Key（优先级：环境变量 > 本地文件 > 配置文件）"""
    # 1. 环境变量（GitHub Actions / Docker）
    env_key = os.environ.get('BARK_DEVICE_KEY', '')
    if env_key:
        return env_key
    
    # 2. 本地文件
    if os.path.exists(BARK_KEY_FILE):
        with open(BARK_KEY_FILE, 'r') as f:
            key = f.read().strip()
            if key:
                return key
    
    # 3. 配置文件
    return BARK_CONFIG.get('device_key', '')


def save_device_key(key: str):
    """保存 Bark Device Key"""
    with open(BARK_KEY_FILE, 'w') as f:
        f.write(key.strip())
    logger.info("Bark Device Key 已保存")


def send_bark(title: str, body: str, url: str = '', group: str = None, 
              sound: str = None, icon: str = None, auto_copy: bool = True) -> bool:
    """
    通过 Bark 发送推送通知到手机
    
    Bark API 格式: https://api.day.app/{device_key}/{title}/{body}?param=value
    
    Args:
        title: 通知标题
        body: 通知正文
        url: 点击通知跳转的URL（可选）
        group: 消息分组
        sound: 通知声音
        auto_copy: 是否自动复制正文到剪贴板
    
    Returns:
        bool: 是否发送成功
    """
    device_key = get_device_key()
    if not device_key:
        logger.warning("未配置 Bark Device Key，跳过推送")
        return False
    
    from urllib.parse import quote
    
    # Bark API 路径格式: /{device_key}/{title}/{body}
    # 中文和特殊字符需要 URL 编码
    api_url = f"{BARK_SERVER}/{device_key}/{quote(title, safe='')}/{quote(body, safe='')}"
    
    # 附加参数通过 query string
    params = []
    if group:
        params.append(f"group={quote(group, safe='')}")
    if sound:
        params.append(f"sound={quote(sound, safe='')}")
    if icon:
        params.append(f"icon={quote(icon, safe='')}")
    if auto_copy:
        params.append("autoCopy=1")
    if url:
        params.append(f"url={quote(url, safe='')}")
    
    if params:
        api_url += "?" + "&".join(params)
    
    try:
        resp = requests.get(api_url, timeout=10)
        result = resp.json()
        
        if result.get('code') == 200:
            logger.info(f"Bark 推送成功: {title}")
            return True
        else:
            logger.warning(f"Bark 推送失败: {result.get('message', '未知错误')}")
            return False
    except Exception as e:
        logger.error(f"Bark 推送异常: {e}")
        return False


def send_bark_with_markdown(title: str, markdown_content: str, group: str = None) -> bool:
    """
    通过 Bark 发送推送（Bark v2.0+ 支持 Markdown）
    把核心信息浓缩后发送
    """
    device_key = get_device_key()
    if not device_key:
        return False
    
    from urllib.parse import quote
    
    # 截取关键信息，Bark 推送不宜过长
    max_body_len = 500
    body = markdown_content[:max_body_len]
    if len(markdown_content) > max_body_len:
        body += "..."
    
    api_url = f"{BARK_SERVER}/{device_key}/{quote(title, safe='')}/{quote(body, safe='')}"
    
    params = []
    g = group or BARK_CONFIG.get('group', 'A股短线跟踪')
    if g:
        params.append(f"group={quote(g, safe='')}")
    s = BARK_CONFIG.get('sound', 'birdsong')
    if s:
        params.append(f"sound={quote(s, safe='')}")
    if BARK_CONFIG.get('auto_copy', True):
        params.append("autoCopy=1")
    
    if params:
        api_url += "?" + "&".join(params)
    
    try:
        resp = requests.get(api_url, timeout=10)
        result = resp.json()
        if result.get('code') == 200:
            logger.info(f"Bark 推送成功: {title}")
            return True
        else:
            logger.warning(f"Bark 推送失败: {result.get('message')}")
            return False
    except Exception as e:
        logger.error(f"Bark 推送异常: {e}")
        return False


def build_push_summary(pool: list, indices: dict, report_type: str) -> tuple:
    """
    根据报告类型构建 Bark 推送摘要
    
    Returns:
        (title, body) 元组
    """
    today = datetime.now()
    time_str = today.strftime('%H:%M')
    weekday_map = ['一','二','三','四','五','六','日']
    weekday = weekday_map[today.weekday()]
    
    # 指数摘要
    index_lines = []
    if indices:
        for name in ['上证指数', '深证成指', '创业板指', '沪深300']:
            data = indices.get(name, {})
            if data:
                pct = data.get('pct_change', 0)
                sign = '+' if pct > 0 else ''
                index_lines.append(f"{name}: {data['price']:.0f} ({sign}{pct:.2f}%)")
    
    # 池内标的摘要
    stock_lines = []
    triggered = []
    
    for s in pool:
        pct = s.get('pct_change', 0)
        sign = '+' if pct > 0 else ''
        price = s.get('current_price', 0)
        style = '🟢' if s.get('style') == 'conservative' else '🔴'
        
        # 信号判断
        signal = ''
        buy_low = s.get('buy_low', 0)
        buy_high = s.get('buy_high', 0)
        target1 = s.get('target1', 0)
        stop = s.get('stop_loss', 0)
        
        if buy_low <= price <= buy_high:
            signal = '💰买进'
            triggered.append(f"{style}{s['name']} 买进区间 {buy_low}-{buy_high}")
        elif price >= target1:
            signal = '🎯达标'
            triggered.append(f"{style}{s['name']} 到达目标 {target1}")
        elif price <= stop:
            signal = '⛔止损'
            triggered.append(f"{style}{s['name']} 触发止损 {stop}")
        elif price < buy_low:
            signal = '⏳观察'
        elif price > buy_high:
            signal = '📈持有'
        else:
            signal = '—'
        
        stock_lines.append(f"{style}{s['name']} {price} {sign}{pct:.2f}% {signal}")
    
    # 构建标题和正文
    if report_type == 'pre_market':
        title = f"📊 盘前精选 · 周{weekday}"
        body_parts = [
            f"【{today.strftime('%m/%d')} 盘前推送】",
            "",
            "━━ 指数 ━━",
            *index_lines,
            "",
            "━━ 精选池 ━━",
            *stock_lines,
        ]
        if triggered:
            body_parts.extend(["", "⚡ 信号:", *triggered])
    
    elif report_type == 'close':
        up = sum(1 for s in pool if s.get('pct_change', 0) > 0)
        down = sum(1 for s in pool if s.get('pct_change', 0) < 0)
        title = f"🔔 收盘 · 周{weekday} {time_str}"
        body_parts = [
            f"【{today.strftime('%m/%d')} 收盘总结】",
            f"📈{up}只涨 📉{down}只跌",
            "",
            "━━ 指数 ━━",
            *index_lines,
            "",
            "━━ 精选池 ━━",
            *stock_lines,
        ]
        if triggered:
            body_parts.extend(["", "⚡ 信号:", *triggered])
    
    else:
        type_names = {
            'intraday_1': f'盘中更新#1 ({time_str})',
            'midday': f'午间复盘 ({time_str})',
            'intraday_3': f'盘中更新#3 ({time_str})',
        }
        name = type_names.get(report_type, f'盘中更新 ({time_str})')
        title = f"📈 {name}"
        body_parts = [
            f"【{today.strftime('%m/%d')} {name}】",
            "",
            "━━ 指数 ━━",
            *index_lines,
            "",
            "━━ 精选池 ━━",
            *stock_lines,
        ]
        if triggered:
            body_parts.extend(["", "⚡ 信号:", *triggered])
    
    body = '\n'.join(body_parts)
    
    # 如果正文太长，精简
    if len(body) > 500:
        body = '\n'.join(body_parts[:len(body_parts)//2]) + '\n...\n📱 详情查看报告中心'
    
    return title, body


def save_report(html_content: str, report_type: str) -> str:
    """
    保存报告到本地文件系统（与之前相同）
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_{report_type}.html"
    filepath = os.path.join(REPORTS_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    latest_path = os.path.join(REPORTS_DIR, f'latest_{report_type}.html')
    with open(latest_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    public_path = os.path.join(PUBLIC_DIR, f'{report_type}.html')
    shutil.copy(latest_path, public_path)
    
    _update_index_html()
    
    logger.info(f"报告已保存: {filepath}")
    return filepath


def _update_index_html():
    """更新报告索引页面"""
    report_types = {
        'pre_market': '📊 盘前精选推送',
        'intraday_1': '📈 盘中更新#1 (10:30)',
        'midday': '🕐 午间复盘 (11:30)',
        'intraday_3': '📈 盘中更新#3 (14:00)',
        'close': '🔔 收盘总结 (15:00)',
    }
    
    links = []
    for rtype, rname in report_types.items():
        filepath = os.path.join(PUBLIC_DIR, f'{rtype}.html')
        if os.path.exists(filepath):
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            links.append(f'<li><a href="{rtype}.html">{rname}</a> — {mtime.strftime("%H:%M:%S")}</li>')
    
    if not links:
        links.append('<li>暂无报告，等待定时任务触发...</li>')
    
    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股短线跟踪系统 — 报告中心</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #f5f6fa; padding: 20px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg,#1a1a2e,#16213e); color: #fff; padding: 30px; border-radius: 12px; text-align: center; margin-bottom: 20px; }}
        .header h1 {{ font-size: 24px; margin-bottom: 5px; }}
        .header p {{ opacity: 0.8; font-size: 14px; }}
        .card {{ background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .card h2 {{ font-size: 18px; color: #2c3e50; margin-bottom: 15px; border-bottom: 2px solid #3498db; padding-bottom: 8px; }}
        .card ul {{ list-style: none; }}
        .card li {{ padding: 10px; border-bottom: 1px solid #f0f0f0; }}
        .card li:last-child {{ border-bottom: none; }}
        .card a {{ color: #2980b9; text-decoration: none; font-size: 15px; }}
        .card a:hover {{ color: #e74c3c; }}
        .status {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
        .status.active {{ background: #27ae60; }}
        .bark-status {{ background: #eaf2f8; padding: 10px; border-radius: 6px; margin: 10px 0; font-size: 13px; }}
        .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; }}
    </style>
    <meta http-equiv="refresh" content="300">
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 A股短线实时跟踪系统</h1>
            <p>报告中心 · {datetime.now().strftime('%Y年%m月%d日 %H:%M')} 更新</p>
        </div>
        <div class="card">
            <h2>📱 推送状态</h2>
            <div class="bark-status">
                {'🟢 Bark 推送已配置' if get_device_key() else '🔴 未配置 Bark，请运行: python3 main.py setup_bark'}
            </div>
        </div>
        <div class="card">
            <h2>📋 最新报告</h2>
            <ul>
                {''.join(links)}
            </ul>
        </div>
        <div class="card">
            <h2>⏰ 推送时间表</h2>
            <ul>
                <li><span class="status active"></span> 09:00 — 盘前精选推送（选股+买卖价+隔夜资讯）</li>
                <li><span class="status active"></span> 10:30 — 盘中更新#1（开盘1小时走势）</li>
                <li><span class="status active"></span> 11:30 — 午间复盘（半日回顾+午后展望）</li>
                <li><span class="status active"></span> 14:00 — 盘中更新#3（午后走势+尾盘策略）</li>
                <li><span class="status active"></span> 15:00 — 收盘总结（全天回顾+明日预判）</li>
            </ul>
        </div>
        <div class="footer">
            <p>⚠️ 本报告由AI自动生成，仅供参考，不构成个人投资建议。股市有风险，投资需谨慎。</p>
        </div>
    </div>
</body>
</html>"""
    
    index_path = os.path.join(PUBLIC_DIR, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)


def send_report(to_email: str = '', subject: str = '', html_content: str = '', 
                plain_text: str = '') -> bool:
    """兼容旧接口"""
    return True


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        key = get_device_key()
        if key:
            print(f"Device Key: {key[:8]}...")
            send_bark("🧪 Bark 推送测试", "A股短线跟踪系统已就绪，Bark 通道测试成功！", 
                       group="A股短线跟踪", sound="birdsong")
        else:
            print("未配置 Device Key")
    else:
        print(f"Bark 推送模块就绪")
        print(f"Device Key: {'已配置' if get_device_key() else '未配置'}")
