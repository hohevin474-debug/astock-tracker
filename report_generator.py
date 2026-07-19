"""
A股短线跟踪系统 — 报告生成器
生成HTML格式的盘前推送、盘中更新、收盘总结报告
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import yaml
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)


def _get_weekday_cn(date: datetime = None) -> str:
    """获取中文星期"""
    if date is None:
        date = datetime.now()
    weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    return weekdays[date.weekday()]


def _format_amount(amount: float) -> str:
    """格式化金额"""
    if amount >= 1e8:
        return f"{amount/1e8:.1f}亿"
    elif amount >= 1e4:
        return f"{amount/1e4:.0f}万"
    return str(amount)


def _format_market_cap(cap: float) -> str:
    """格式化市值"""
    if cap >= 1e12:
        return f"{cap/1e12:.2f}万亿"
    elif cap >= 1e8:
        return f"{cap/1e8:.0f}亿"
    return str(cap)


def _price_color(pct: float) -> str:
    """涨跌颜色"""
    if pct > 0:
        return '#e74c3c'
    elif pct < 0:
        return '#27ae60'
    return '#7f8c8d'


def _pct_str(pct: float) -> str:
    """涨跌幅格式化"""
    if pct > 0:
        return f'+{pct:.2f}%'
    elif pct < 0:
        return f'{pct:.2f}%'
    return '0.00%'


def _signal_badge(stock: dict) -> str:
    """生成交易信号标签"""
    badges = []
    
    price = stock.get('current_price', 0)
    buy_low = stock.get('buy_low', 0)
    buy_high = stock.get('buy_high', 0)
    target1 = stock.get('target1', 0)
    stop = stock.get('stop_loss', 0)
    
    if buy_low <= price <= buy_high:
        badges.append('<span style="background:#27ae60;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">🟢 买进区间</span>')
    elif price >= target1:
        badges.append('<span style="background:#e74c3c;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">🎯 到达目标1</span>')
    elif price <= stop:
        badges.append('<span style="background:#c0392b;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">⛔ 触发止损</span>')
    elif price < buy_low:
        badges.append('<span style="background:#f39c12;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">⏳ 接近买进</span>')
    elif price > buy_high and price < target1:
        badges.append('<span style="background:#3498db;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">📈 持有观望</span>')
    
    return ' '.join(badges) if badges else ''


def _build_pool_table(stocks: list) -> str:
    """构建精选池表格"""
    rows = []
    for s in stocks:
        style_tag = '🟢 稳健' if s.get('style') == 'conservative' else '🔴 进取'
        signal = _signal_badge(s)
        rows.append(f"""
        <tr>
            <td>{s.get('code', '')}</td>
            <td>{s.get('name', '')}</td>
            <td>{style_tag}</td>
            <td style="font-weight:bold;">{s.get('current_price', 'N/A')}</td>
            <td style="color:{_price_color(s.get('pct_change', 0))}">{_pct_str(s.get('pct_change', 0))}</td>
            <td>{s.get('buy_zone', 'N/A')}</td>
            <td>{s.get('target1', 'N/A')}</td>
            <td>{s.get('target2', 'N/A')}</td>
            <td style="color:#e74c3c">{s.get('stop_loss', 'N/A')}</td>
            <td>{signal}</td>
        </tr>""")
    
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
            <tr style="background:#2c3e50;color:#fff;">
                <th>代码</th><th>名称</th><th>风格</th><th>现价</th><th>涨跌幅</th>
                <th>买进区间</th><th>目标1</th><th>目标2</th><th>止损</th><th>信号</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>"""


def _build_index_table(indices: dict) -> str:
    """构建指数行情表格"""
    if not indices:
        return '<p>暂无指数数据</p>'
    
    rows = []
    for name, data in indices.items():
        pct = data.get('pct_change', 0)
        rows.append(f"""
        <tr>
            <td><strong>{name}</strong></td>
            <td>{data.get('price', 'N/A')}</td>
            <td style="color:{_price_color(pct)};font-weight:bold;">{_pct_str(pct)}</td>
            <td>{_format_amount(data.get('amount', 0))}</td>
        </tr>""")
    
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
            <tr style="background:#34495e;color:#fff;">
                <th>指数</th><th>点位</th><th>涨跌幅</th><th>成交额</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>"""


def _build_hot_sectors(hotness: dict) -> str:
    """构建热门板块"""
    if not hotness:
        return '<p>暂无板块数据</p>'
    
    rows = []
    for name, data in list(hotness.items())[:8]:
        pct = data.get('pct_change', 0)
        rows.append(f"""
        <tr>
            <td>{name}</td>
            <td style="color:{_price_color(pct)};font-weight:bold;">{_pct_str(pct)}</td>
            <td>{_format_amount(data.get('net_flow', 0))}</td>
        </tr>""")
    
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
            <tr style="background:#16a085;color:#fff;">
                <th>板块</th><th>涨跌幅</th><th>主力净流入</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>"""


def generate_pre_market_report(pool: list, indices: dict, hot_sectors: dict, 
                                limit_up_stats: dict, overnight_news: str = '') -> str:
    """
    生成盘前推送报告（HTML格式）
    """
    today = datetime.now()
    date_str = today.strftime('%Y年%m月%d日')
    weekday = _get_weekday_cn(today)
    
    conservative_stocks = [s for s in pool if s.get('style') == 'conservative']
    aggressive_stocks = [s for s in pool if s.get('style') == 'aggressive']
    
    # 今日重点关注（选2-3只）
    focus_stocks = []
    for s in pool:
        pct = s.get('pct_change', 0)
        if pct != 0:
            focus_stocks.append(s)
    if not focus_stocks:
        focus_stocks = pool[:3]
    
    focus_html = ''
    for s in focus_stocks[:3]:
        pct = s.get('pct_change', 0)
        focus_html += f"""
        <div style="margin:5px 0;padding:8px;background:#f8f9fa;border-left:3px solid #3498db;">
            <strong>{s.get('code', '')} {s.get('name', '')}</strong>
            <span style="color:{_price_color(pct)};margin-left:10px;">{_pct_str(pct)}</span>
            <br><small>{s.get('logic', '')}</small>
        </div>"""
    
    overnight_section = ''
    if overnight_news:
        overnight_section = f"""
        <div style="background:#fff3cd;padding:12px;border-radius:6px;margin:10px 0;">
            <h4 style="margin:0 0 5px 0;color:#856404;">🌙 隔夜要闻</h4>
            <p style="margin:0;white-space:pre-line;">{overnight_news}</p>
        </div>"""
    
    html = f"""
    <div style="font-family:'Microsoft YaHei','PingFang SC',sans-serif;max-width:700px;margin:0 auto;background:#fff;">
        <!-- 头部 -->
        <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:20px;border-radius:10px 10px 0 0;">
            <h1 style="margin:0;font-size:22px;">📊 A股短线跟踪</h1>
            <p style="margin:5px 0 0 0;font-size:14px;opacity:0.9;">
                {date_str} {weekday} · 盘前精选推送
            </p>
        </div>
        
        <div style="padding:15px;border:1px solid #e0e0e0;border-top:none;">
            
            <!-- 指数概览 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:5px;">📈 主要指数</h3>
            {_build_index_table(indices)}
            
            {overnight_section}
            
            <!-- 今日重点关注 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #e74c3c;padding-bottom:5px;">🔥 今日重点关注</h3>
            {focus_html}
            
            <!-- 精选池 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #27ae60;padding-bottom:5px;">
                🎯 本周精选池 
                <span style="font-size:13px;font-weight:normal;">
                    （{len(conservative_stocks)}只稳健 + {len(aggressive_stocks)}只进取）
                </span>
            </h3>
            {_build_pool_table(pool)}
            
            <!-- 选股逻辑说明 -->
            <div style="background:#eaf2f8;padding:10px;border-radius:6px;margin:10px 0;font-size:12px;">
                <strong>📋 选股逻辑：</strong><br>
                🟢 <strong>稳健轨</strong>：市值200亿+ | PE 10-30x | 低波动 | 流动性充裕 | 均线支撑明确<br>
                🔴 <strong>进取轨</strong>：近期放量 | 换手率活跃 | 资金关注度高 | 技术面弹性标的<br>
                ⚠️ 买进区间基于支撑位和均线系统计算，目标价基于阻力位和布林带上轨
            </div>
            
            <!-- 热门板块 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #16a085;padding-bottom:5px;">🏭 热门板块</h3>
            {_build_hot_sectors(hot_sectors)}
            
            <!-- 涨停统计 -->
            <div style="background:#f0f3f5;padding:10px;border-radius:6px;margin:10px 0;">
                <strong>📊 今日涨停统计：</strong>
                <span style="color:#e74c3c;font-weight:bold;font-size:16px;">{limit_up_stats.get('limit_up_count', 'N/A')}</span> 只涨停
            </div>
            
            <!-- 免责声明 -->
            <div style="border-top:1px solid #ddd;margin-top:15px;padding-top:10px;font-size:11px;color:#999;">
                <p>⚠️ <strong>免责声明：</strong>本报告由AI自动生成，仅供参考，不构成任何个人投资建议。股市有风险，投资需谨慎。报告中的数据来源于公开信息，AI不保证其准确性和完整性。过往表现不代表未来收益。</p>
                <p>📧 如需调整推送频率或停止接收，请联系系统管理员。</p>
            </div>
        </div>
    </div>"""
    
    return html


def generate_intraday_update(pool: list, indices: dict, hot_sectors: dict, 
                              update_type: str = 'intraday') -> str:
    """
    生成盘中更新报告
    update_type: 'intraday_1' (10:30), 'midday' (11:30), 'intraday_3' (14:00), 'close' (15:00)
    """
    today = datetime.now()
    date_str = today.strftime('%Y年%m月%d日')
    time_str = today.strftime('%H:%M')
    weekday = _get_weekday_cn(today)
    
    # 标题映射
    title_map = {
        'intraday_1': '📊 盘中更新#1 — 开盘1小时走势',
        'midday': '🕐 午间更新 — 半日复盘 + 午后展望',
        'intraday_3': '📊 盘中更新#3 — 午后走势 + 尾盘策略',
        'close': '🔔 收盘总结 — 全天回顾 + 明日预判',
    }
    
    title = title_map.get(update_type, f'📊 盘中更新 — {time_str}')
    
    # 触发信号的标的
    triggered = []
    for s in pool:
        price = s.get('current_price', 0)
        if price > 0:
            s['_triggered'] = (
                (s.get('buy_low', 0) <= price <= s.get('buy_high', 0)) or
                (price >= s.get('target1', 0)) or
                (price <= s.get('stop_loss', 0))
            )
            if s['_triggered']:
                triggered.append(s)
    
    # 涨跌统计
    up_count = sum(1 for s in pool if s.get('pct_change', 0) > 0)
    down_count = sum(1 for s in pool if s.get('pct_change', 0) < 0)
    
    triggered_html = ''
    if triggered:
        for s in triggered:
            triggered_html += f"""
            <div style="margin:5px 0;padding:8px;background:#fef9e7;border-left:3px solid #f39c12;">
                <strong>{s.get('code', '')} {s.get('name', '')}</strong>
                <span style="color:{_price_color(s.get('pct_change', 0))};margin-left:10px;">{_pct_str(s.get('pct_change', 0))}</span>
                <span style="margin-left:10px;">现价: {s.get('current_price', 'N/A')}</span>
                <br><small>{_signal_badge(s)}</small>
            </div>"""
    else:
        triggered_html = '<p style="color:#7f8c8d;">暂无标的触发买卖信号</p>'
    
    # 收盘特有内容
    close_extra = ''
    if update_type == 'close':
        # 当天表现最佳/最差
        sorted_pool = sorted(pool, key=lambda x: x.get('pct_change', 0), reverse=True)
        best = sorted_pool[:2] if sorted_pool else []
        worst = sorted_pool[-2:] if len(sorted_pool) >= 2 else []
        
        best_html = ''.join([f"<li>{s.get('name', '')} {_pct_str(s.get('pct_change', 0))}</li>" for s in best])
        worst_html = ''.join([f"<li>{s.get('name', '')} {_pct_str(s.get('pct_change', 0))}</li>" for s in worst])
        
        close_extra = f"""
        <h3 style="color:#2c3e50;border-bottom:2px solid #e74c3c;padding-bottom:5px;">🏆 今日表现</h3>
        <div style="display:flex;gap:10px;">
            <div style="flex:1;background:#fdedec;padding:10px;border-radius:6px;">
                <strong>📈 涨幅前2</strong><ul>{best_html}</ul>
            </div>
            <div style="flex:1;background:#eafaf1;padding:10px;border-radius:6px;">
                <strong>📉 跌幅前2</strong><ul>{worst_html}</ul>
            </div>
        </div>
        
        <h3 style="color:#2c3e50;border-bottom:2px solid #8e44ad;padding-bottom:5px;">🔮 明日预判</h3>
        <div style="background:#f3e5f5;padding:10px;border-radius:6px;">
            <p style="margin:5px 0;">• 关注明日开盘资金面变化，重点观察竞价阶段量能</p>
            <p style="margin:5px 0;">• 精选池标的如有触及目标价，建议分批止盈</p>
            <p style="margin:5px 0;">• 关注今晚美股走势和消息面，可能影响明日A股情绪</p>
        </div>"""
    
    html = f"""
    <div style="font-family:'Microsoft YaHei','PingFang SC',sans-serif;max-width:700px;margin:0 auto;background:#fff;">
        <!-- 头部 -->
        <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:20px;border-radius:10px 10px 0 0;">
            <h1 style="margin:0;font-size:22px;">{title}</h1>
            <p style="margin:5px 0 0 0;font-size:14px;opacity:0.9;">
                {date_str} {weekday} · {time_str}
            </p>
        </div>
        
        <div style="padding:15px;border:1px solid #e0e0e0;border-top:none;">
            
            <!-- 市场概览 -->
            <div style="display:flex;gap:10px;margin-bottom:15px;">
                <div style="flex:1;background:#eaf2f8;padding:10px;border-radius:6px;text-align:center;">
                    <div style="font-size:12px;color:#7f8c8d;">精选池上涨</div>
                    <div style="font-size:20px;color:#e74c3c;font-weight:bold;">{up_count}</div>
                </div>
                <div style="flex:1;background:#fdedec;padding:10px;border-radius:6px;text-align:center;">
                    <div style="font-size:12px;color:#7f8c8d;">精选池下跌</div>
                    <div style="font-size:20px;color:#27ae60;font-weight:bold;">{down_count}</div>
                </div>
                <div style="flex:1;background:#fef9e7;padding:10px;border-radius:6px;text-align:center;">
                    <div style="font-size:12px;color:#7f8c8d;">信号触发</div>
                    <div style="font-size:20px;color:#f39c12;font-weight:bold;">{len(triggered)}</div>
                </div>
            </div>
            
            <!-- 指数 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:5px;">📈 主要指数</h3>
            {_build_index_table(indices)}
            
            <!-- 信号触发 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #f39c12;padding-bottom:5px;">⚡ 信号触发标的</h3>
            {triggered_html}
            
            <!-- 精选池 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #27ae60;padding-bottom:5px;">🎯 精选池实时表现</h3>
            {_build_pool_table(pool)}
            
            {close_extra}
            
            <!-- 热门板块 -->
            <h3 style="color:#2c3e50;border-bottom:2px solid #16a085;padding-bottom:5px;">🏭 热门板块</h3>
            {_build_hot_sectors(hot_sectors)}
            
            <!-- 免责声明 -->
            <div style="border-top:1px solid #ddd;margin-top:15px;padding-top:10px;font-size:11px;color:#999;">
                <p>⚠️ <strong>免责声明：</strong>本报告由AI自动生成，仅供参考，不构成任何个人投资建议。股市有风险，投资需谨慎。</p>
            </div>
        </div>
    </div>"""
    
    return html


def generate_plain_text_report(pool: list, indices: dict, update_type: str = 'pre_market') -> str:
    """
    生成纯文本版报告（备用，当HTML邮件不可用时）
    """
    today = datetime.now()
    date_str = today.strftime('%Y年%m月%d日')
    weekday = _get_weekday_cn(today)
    
    lines = []
    lines.append("=" * 60)
    
    if update_type == 'pre_market':
        lines.append(f"📊 A股短线跟踪 — {date_str} {weekday} 盘前推送")
    elif update_type == 'close':
        lines.append(f"📊 A股短线跟踪 — {date_str} {weekday} 收盘总结")
    else:
        lines.append(f"📊 A股短线跟踪 — {date_str} {weekday} 盘中更新")
    
    lines.append("=" * 60)
    lines.append("")
    
    # 指数
    if indices:
        lines.append("【主要指数】")
        for name, data in indices.items():
            pct = data.get('pct_change', 0)
            sign = '+' if pct > 0 else ''
            lines.append(f"  {name}: {data.get('price', 'N/A')} ({sign}{pct:.2f}%)")
        lines.append("")
    
    # 精选池
    lines.append(f"【本周精选池】({len(pool)}只标的)")
    lines.append(f"{'代码':<10}{'名称':<10}{'风格':<8}{'现价':<10}{'涨跌幅':<10}{'买进区间':<15}{'目标1':<10}{'止损':<10}")
    lines.append("-" * 85)
    
    for s in pool:
        style = '稳健' if s.get('style') == 'conservative' else '进取'
        pct = s.get('pct_change', 0)
        sign = '+' if pct > 0 else ''
        price_str = f"{s.get('current_price', 'N/A')}"
        pct_str_full = f"{sign}{pct:.2f}%"
        line = (f"{s.get('code', ''):<10}{s.get('name', ''):<10}{style:<8}"
                f"{price_str:<10}{pct_str_full:<10}"
                f"{s.get('buy_zone', 'N/A'):<15}{s.get('target1', 'N/A'):<10}{s.get('stop_loss', 'N/A'):<10}")
        lines.append(line)
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("⚠️ 本报告仅供参考，不构成个人投资建议。股市有风险，投资需谨慎。")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    # 测试
    test_pool = [
        {
            'code': '000001', 'name': '平安银行', 'style': 'conservative',
            'current_price': 12.50, 'pct_change': 1.2,
            'buy_zone': '12.0-12.8', 'buy_low': 12.0, 'buy_high': 12.8,
            'target1': 13.50, 'target2': 14.80, 'stop_loss': 11.88,
            'logic': '低估值蓝筹 | PE=12 | 流动性充裕',
        },
        {
            'code': '300750', 'name': '宁德时代', 'style': 'aggressive',
            'current_price': 210.00, 'pct_change': 3.5,
            'buy_zone': '205-215', 'buy_low': 205, 'buy_high': 215,
            'target1': 226.80, 'target2': 241.50, 'stop_loss': 199.50,
            'logic': '短线活跃 | 换手率=5% | 资金关注度高',
        },
    ]
    
    test_indices = {
        '上证指数': {'price': 3350.50, 'pct_change': 0.35, 'amount': 350000000000},
        '深证成指': {'price': 10800.20, 'pct_change': -0.22, 'amount': 280000000000},
    }
    
    test_sectors = {
        '半导体': {'pct_change': 3.5, 'net_flow': 2500000000},
        '新能源': {'pct_change': 2.1, 'net_flow': 1800000000},
    }
    
    html = generate_pre_market_report(test_pool, test_indices, test_sectors, {'limit_up_count': 35})
    print(html[:500])
