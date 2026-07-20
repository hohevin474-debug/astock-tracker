"""
A股短线跟踪系统 — 持仓跟踪引擎
对精选池中每只股票持续跟踪，直到触发卖出条件：
  止盈条件：达到目标价1 / 目标价2
  止损条件：跌破止损线
  趋势恶化：连续跌破关键均线 / MACD死叉 / RSI超买反转
  时间止损：持仓超过N天未达目标，重新评估

每天更新：持仓状态、当前盈亏、技术面变化、目标价调整
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import yaml
import os
import json

from market_data import get_realtime_quotes, get_market_index
from price_model import get_stock_full_analysis

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

POSITION_FILE = os.path.join(os.path.dirname(__file__), '.positions.json')


# ========== 持仓数据管理 ==========

def load_positions() -> list:
    """加载当前持仓"""
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, 'r') as f:
            return json.load(f)
    return []


def save_positions(positions: list):
    """保存持仓"""
    with open(POSITION_FILE, 'w') as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def init_position(stock: dict, entry_price: float = None) -> dict:
    """
    初始化持仓记录
    stock: 来自精选池的标的字典
    """
    now = datetime.now()
    price = entry_price or stock.get('current_price', 0)
    
    return {
        'code': stock['code'],
        'name': stock['name'],
        'style': stock.get('style', 'unknown'),
        'entry_date': now.strftime('%Y-%m-%d'),
        'entry_price': price,
        'entry_time': now.isoformat(),
        
        # 原始目标（来自选股时的定价）
        'target1': stock.get('target1', 0),
        'target2': stock.get('target2', 0),
        'stop_loss': stock.get('stop_loss', 0),
        'buy_zone': stock.get('buy_zone', ''),
        
        # 实时数据（每次更新）
        'current_price': price,
        'pct_change': 0,
        'profit_pct': 0,
        'profit_amount': 0,
        
        # 技术分析
        'support': stock.get('support', price * 0.95),
        'resistance': stock.get('resistance', price * 1.10),
        'ma20': price,
        'rsi': 50,
        'macd_signal': 'N/A',
        'volume_trend': 'N/A',
        'trend': '持有',  # 持有/走弱/走强
        
        # 信号
        'signals': [],       # 当前触发的信号列表
        'action': '持有',    # 持有/加仓/减仓/卖出/观望
        'action_reason': '',
        
        # 历史
        'history': [{
            'date': now.strftime('%Y-%m-%d %H:%M'),
            'price': price,
            'event': '建仓',
            'note': f"入选精选池，买进区间 {stock.get('buy_zone', 'N/A')}"
        }],
        
        # 状态
        'status': 'active',  # active / closed
        'closed_date': None,
        'closed_price': None,
        'closed_reason': None,
    }


def update_positions_from_pool(pool: list) -> list:
    """
    从精选池更新持仓：新标的加入，已有标的保持
    """
    positions = load_positions()
    existing_codes = {p['code'] for p in positions}
    
    for stock in pool:
        if stock['code'] not in existing_codes:
            pos = init_position(stock)
            positions.append(pos)
            logger.info(f"新持仓: {stock['code']} {stock['name']} @ {pos['entry_price']}")
    
    save_positions(positions)
    return positions


# ========== 实时分析 ==========

def analyze_position(pos: dict) -> dict:
    """
    分析单个持仓，更新技术指标和信号
    返回更新后的持仓字典
    """
    code = pos['code']
    
    # 获取实时行情
    try:
        quotes = get_realtime_quotes(codes=[code])
        if not quotes.empty:
            row = quotes.iloc[0]
            current_price = row.get('price', pos['current_price'])
            prev_close = row.get('prev_close', current_price)
            pct_change = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
            
            pos['current_price'] = current_price
            pos['pct_change'] = round(pct_change, 2)
            
            # 盈亏计算
            if pos['entry_price'] > 0:
                pos['profit_pct'] = round((current_price - pos['entry_price']) / pos['entry_price'] * 100, 2)
                pos['profit_amount'] = round(current_price - pos['entry_price'], 2)
    except Exception as e:
        logger.warning(f"获取 {code} 实时行情失败: {e}")
    
    current_price = pos['current_price']
    
    # 获取技术分析
    try:
        analysis = get_stock_full_analysis(code)
        if analysis and 'error' not in analysis:
            pos['support'] = analysis.get('support_1', pos['support'])
            pos['resistance'] = analysis.get('resistance_1', pos['resistance'])
            pos['ma20'] = analysis.get('ma20', pos['ma20'])
            pos['rsi'] = analysis.get('rsi', 50)
            pos['macd_signal'] = analysis.get('signal', 'N/A')
            pos['volume_trend'] = analysis.get('trend', 'N/A')
    except Exception as e:
        logger.warning(f"获取 {code} 技术分析失败: {e}")
    
    # ========== 信号判断 ==========
    signals = []
    action = '持有'
    action_reason = ''
    
    # 1. 止盈信号
    if current_price >= pos['target2']:
        signals.append(f"🎯 到达目标价2 ({pos['target2']})，盈利 {pos['profit_pct']:+.1f}%")
        action = '卖出'
        action_reason = f"到达目标价2 {pos['target2']}，建议全部止盈"
    elif current_price >= pos['target1']:
        signals.append(f"🎯 到达目标价1 ({pos['target1']})，盈利 {pos['profit_pct']:+.1f}%")
        action = '减仓'
        action_reason = f"到达目标价1 {pos['target1']}，建议减仓50%，剩余持仓上移止损至成本价"
    
    # 2. 止损信号
    elif current_price <= pos['stop_loss']:
        signals.append(f"⛔ 触发止损线 ({pos['stop_loss']})，亏损 {pos['profit_pct']:+.1f}%")
        action = '卖出'
        action_reason = f"跌破止损线 {pos['stop_loss']}，严格止损"
    
    # 3. 趋势恶化信号（仅在未触发止损/止盈时判断）
    elif pos['profit_pct'] < -3:
        rsi = pos.get('rsi', 50)
        macd = pos.get('macd_signal', '')
        
        if rsi < 30:
            signals.append(f"⚠️ RSI={rsi} 超卖，短期可能反弹，暂持观望")
            action = '观望'
            action_reason = f"RSI超卖({rsi})但未触及止损，观察反弹力度"
        elif macd == '死叉':
            signals.append(f"⚠️ MACD死叉，趋势转弱")
            action = '减仓'
            action_reason = f"MACD死叉 + 浮亏{pos['profit_pct']:.1f}%，建议减仓控制风险"
        elif pos['profit_pct'] < -5:
            signals.append(f"🔴 浮亏超过5%，密切关注止损线")
            action = '观望'
            action_reason = f"浮亏{pos['profit_pct']:.1f}%，距离止损线{pos['stop_loss']}还有{round((current_price-pos['stop_loss'])/current_price*100,1)}%空间"
    
    # 4. 强势持有信号
    elif pos['profit_pct'] > 5:
        rsi = pos.get('rsi', 50)
        if rsi > 70:
            signals.append(f"📈 强势上涨中 (RSI={rsi})，但已超买，注意回撤风险")
            action = '持有'
            action_reason = f"盈利{pos['profit_pct']:.1f}%，RSI超买({rsi})，建议上移止损保护利润"
        else:
            signals.append(f"📈 趋势向好，盈利 {pos['profit_pct']:+.1f}%")
            action = '持有'
            action_reason = f"趋势健康，建议持有，止损上移至{round(current_price*0.97,2)}"
    
    # 5. 横盘/微利
    else:
        days_held = (datetime.now() - datetime.fromisoformat(pos['entry_time'])).days
        if days_held >= 5 and abs(pos['profit_pct']) < 2:
            signals.append(f"⏰ 持仓{days_held}天，横盘整理，盈亏{pos['profit_pct']:+.1f}%")
            action = '观望'
            action_reason = f"持仓{days_held}天无突破，关注是否换股"
        else:
            action = '持有'
            action_reason = '等待趋势明朗'
    
    pos['signals'] = signals
    pos['action'] = action
    pos['action_reason'] = action_reason
    
    # 趋势判断
    if pos['profit_pct'] > 3:
        pos['trend'] = '走强'
    elif pos['profit_pct'] < -3:
        pos['trend'] = '走弱'
    else:
        pos['trend'] = '持有'
    
    # 记录历史
    today_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    last_event = pos['history'][-1] if pos['history'] else None
    
    # 只在有变化时记录
    if action != '持有' or (last_event and last_event.get('date','')[:10] != datetime.now().strftime('%Y-%m-%d')):
        pos['history'].append({
            'date': today_str,
            'price': current_price,
            'event': action,
            'note': action_reason
        })
        # 只保留最近30条
        if len(pos['history']) > 30:
            pos['history'] = pos['history'][-30:]
    
    # 更新目标价（根据趋势动态调整）
    pos = _adjust_targets(pos)
    
    return pos


def _adjust_targets(pos: dict) -> dict:
    """根据趋势动态调整目标价"""
    current = pos['current_price']
    entry = pos['entry_price']
    
    # 如果涨超目标1但未到目标2，上移止损
    if current >= pos['target1'] and pos['action'] == '减仓':
        pos['stop_loss'] = round(entry, 2)  # 止损上移至成本价
        pos['signals'].append(f"🛡️ 止损已上移至成本价 {entry}")
    
    # 如果趋势走强，适度上移目标
    if pos['trend'] == '走强' and pos['profit_pct'] > 8:
        new_target2 = round(current * 1.10, 2)
        if new_target2 > pos['target2']:
            pos['signals'].append(f"🎯 目标价2上调: {pos['target2']} → {new_target2}")
            pos['target2'] = new_target2
    
    return pos


def close_position(pos: dict, reason: str, close_price: float = None) -> dict:
    """平仓"""
    pos['status'] = 'closed'
    pos['closed_date'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    pos['closed_price'] = close_price or pos['current_price']
    pos['closed_reason'] = reason
    pos['action'] = '已卖出'
    
    final_profit = round((pos['closed_price'] - pos['entry_price']) / pos['entry_price'] * 100, 2)
    pos['history'].append({
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'price': pos['closed_price'],
        'event': f'卖出 ({reason})',
        'note': f"最终盈亏: {final_profit:+.1f}%"
    })
    
    logger.info(f"平仓: {pos['code']} {pos['name']} @ {pos['closed_price']} 盈亏{final_profit:+.1f}% ({reason})")
    return pos


def track_all_positions(pool: list) -> dict:
    """
    跟踪所有持仓，返回分析结果
    返回: {
        'active': [...],     # 活跃持仓
        'alerts': [...],     # 需要推送的警报
        'closed': [...],     # 今日平仓
        'summary': {...},    # 汇总
    }
    """
    # 先更新持仓（新标的加入）
    positions = update_positions_from_pool(pool)
    
    active = []
    alerts = []
    closed_today = []
    
    for pos in positions:
        if pos.get('status') == 'closed':
            # 检查是否今日平仓
            if pos.get('closed_date', '')[:10] == datetime.now().strftime('%Y-%m-%d'):
                closed_today.append(pos)
            continue
        
        # 分析持仓
        pos = analyze_position(pos)
        
        # 判断是否需要平仓
        if pos['action'] == '卖出':
            pos = close_position(pos, pos['action_reason'])
            closed_today.append(pos)
            alerts.append({
                'type': '卖出',
                'title': f"⛔ 卖出信号: {pos['name']}",
                'body': f"{pos['code']} {pos['name']}\n"
                        f"卖出价: {pos['closed_price']}\n"
                        f"盈亏: {pos['profit_pct']:+.1f}%\n"
                        f"原因: {pos['closed_reason']}"
            })
        elif pos['action'] == '减仓':
            alerts.append({
                'type': '减仓',
                'title': f"📉 减仓建议: {pos['name']}",
                'body': f"{pos['code']} {pos['name']}\n"
                        f"现价: {pos['current_price']}\n"
                        f"盈亏: {pos['profit_pct']:+.1f}%\n"
                        f"原因: {pos['action_reason']}"
            })
        elif pos['action'] == '观望' and pos.get('signals'):
            alerts.append({
                'type': '关注',
                'title': f"⚠️ 关注: {pos['name']}",
                'body': f"{pos['code']} {pos['name']}\n"
                        f"现价: {pos['current_price']}\n"
                        f"盈亏: {pos['profit_pct']:+.1f}%\n"
                        + '\n'.join(pos['signals'])
            })
        
        active.append(pos)
    
    # 保存更新后的持仓
    all_positions = active + [p for p in positions if p.get('status') == 'closed']
    save_positions(all_positions)
    
    # 汇总
    total_profit = sum(p.get('profit_pct', 0) for p in active)
    up_count = sum(1 for p in active if p.get('profit_pct', 0) > 0)
    down_count = sum(1 for p in active if p.get('profit_pct', 0) < 0)
    
    summary = {
        'total': len(active),
        'up': up_count,
        'down': down_count,
        'flat': len(active) - up_count - down_count,
        'total_profit_pct': round(total_profit, 2),
        'avg_profit_pct': round(total_profit / len(active), 2) if active else 0,
        'closed_today': len(closed_today),
        'alerts': len(alerts),
    }
    
    return {
        'active': active,
        'alerts': alerts,
        'closed': closed_today,
        'summary': summary,
    }


def build_track_summary(track_result: dict) -> str:
    """构建持仓跟踪摘要（用于 Bark 推送）"""
    active = track_result['active']
    summary = track_result['summary']
    alerts = track_result['alerts']
    
    lines = []
    lines.append(f"【持仓跟踪 · {datetime.now().strftime('%m/%d %H:%M')}】")
    lines.append(f"📊 {summary['total']}只持仓 | 📈{summary['up']}涨 📉{summary['down']}跌")
    lines.append(f"💰 总盈亏: {summary['total_profit_pct']:+.1f}%")
    lines.append("")
    
    # 按盈亏排序
    sorted_positions = sorted(active, key=lambda x: x.get('profit_pct', 0), reverse=True)
    
    for pos in sorted_positions:
        profit = pos.get('profit_pct', 0)
        sign = '+' if profit > 0 else ''
        action = pos.get('action', '持有')
        
        action_icon = {
            '持有': '📌', '观望': '⏳', '减仓': '📉', 
            '卖出': '⛔', '已卖出': '✅'
        }.get(action, '📌')
        
        line = f"{action_icon}{pos['name']} {pos['current_price']} ({sign}{profit:.1f}%)"
        
        # 添加关键信号
        if action in ('减仓', '卖出'):
            line += f" → {action}"
        
        lines.append(line)
    
    # 警报
    if alerts:
        lines.append("")
        lines.append("⚡ 重要信号:")
        for alert in alerts[:3]:  # 最多3条
            lines.append(f"  {alert['title']}")
    
    # 今日平仓
    if track_result['closed']:
        lines.append("")
        lines.append("✅ 今日卖出:")
        for c in track_result['closed']:
            lines.append(f"  {c['name']} @ {c['closed_price']} ({c['closed_reason']})")
    
    return '\n'.join(lines)


def build_daily_analysis(positions: list) -> str:
    """
    生成每日深度分析（更详细的持仓分析报告）
    用于盘中14:00和收盘15:00推送
    """
    active = [p for p in positions if p.get('status') == 'active']
    
    if not active:
        return "暂无活跃持仓"
    
    lines = []
    lines.append("━━━ 持仓深度分析 ━━━")
    lines.append("")
    
    for pos in active:
        name = pos['name']
        code = pos['code']
        profit = pos.get('profit_pct', 0)
        sign = '+' if profit > 0 else ''
        current = pos.get('current_price', 0)
        entry = pos.get('entry_price', 0)
        
        lines.append(f"【{name}】{code}")
        lines.append(f"  成本: {entry} → 现价: {current} ({sign}{profit:.1f}%)")
        lines.append(f"  目标1: {pos.get('target1','N/A')} | 目标2: {pos.get('target2','N/A')} | 止损: {pos.get('stop_loss','N/A')}")
        lines.append(f"  技术: RSI={pos.get('rsi','N/A')} | MACD={pos.get('macd_signal','N/A')} | 量能={pos.get('volume_trend','N/A')}")
        lines.append(f"  支撑: {pos.get('support','N/A')} | 阻力: {pos.get('resistance','N/A')}")
        lines.append(f"  趋势: {pos.get('trend','N/A')} | 建议: {pos.get('action','N/A')}")
        
        if pos.get('signals'):
            for sig in pos['signals'][:2]:
                lines.append(f"  → {sig}")
        
        lines.append("")
    
    # 整体风险评估
    lines.append("━━━ 风险评估 ━━━")
    total_profit = sum(p.get('profit_pct', 0) for p in active)
    avg_profit = total_profit / len(active) if active else 0
    
    if avg_profit > 5:
        lines.append(f"🟢 整体盈利 {avg_profit:+.1f}%，可适度乐观")
        lines.append(f"   建议：上移止损保护利润，关注超买信号")
    elif avg_profit > 0:
        lines.append(f"🟡 微利状态 {avg_profit:+.1f}%，耐心持有")
        lines.append(f"   建议：维持现有仓位，等待趋势明确")
    elif avg_profit > -3:
        lines.append(f"🟠 轻微浮亏 {avg_profit:+.1f}%，密切关注")
        lines.append(f"   建议：检查止损线是否合理，关注MACD变化")
    else:
        lines.append(f"🔴 浮亏扩大 {avg_profit:+.1f}%，需要警惕")
        lines.append(f"   建议：严格止损纪律，审视选股逻辑")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    # 测试
    from stock_screener import generate_weekly_pool
    
    print("生成精选池...")
    pool = generate_weekly_pool(force_refresh=True)
    
    print(f"\n跟踪持仓 ({len(pool)} 只)...")
    result = track_all_positions(pool)
    
    print("\n=== 汇总 ===")
    for k, v in result['summary'].items():
        print(f"  {k}: {v}")
    
    print(f"\n=== 警报 ({len(result['alerts'])} 条) ===")
    for a in result['alerts']:
        print(f"  [{a['type']}] {a['title']}")
    
    print("\n=== 持仓详情 ===")
    for p in result['active']:
        print(f"  {p['code']} {p['name']}: {p['current_price']} "
              f"({p['profit_pct']:+.1f}%) → {p['action']}")
    
    print("\n=== 推送摘要 ===")
    print(build_track_summary(result))
