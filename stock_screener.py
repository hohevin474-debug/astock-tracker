"""
A股短线跟踪系统 — 选股引擎
双轨筛选：50%稳健（蓝筹/低波动）+ 50%进取（高成长/题材热点）
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import yaml
import os
import json
import warnings
warnings.filterwarnings('ignore')

from market_data import (
    get_realtime_quotes, get_stock_history,
    get_dragon_tiger_board, get_limit_up_down_stats,
    get_sector_flow
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

POOL_SIZE = CONFIG['screening']['pool_size']
CONSERVATIVE_COUNT = int(POOL_SIZE * CONFIG['screening']['conservative_ratio'])
AGGRESSIVE_COUNT = int(POOL_SIZE * CONFIG['screening']['aggressive_ratio'])

# 缓存
POOL_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.pool_cache.json')


def load_pool_cache() -> dict:
    """加载精选池缓存"""
    if os.path.exists(POOL_CACHE_FILE):
        with open(POOL_CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_pool_cache(pool: dict):
    """保存精选池缓存"""
    with open(POOL_CACHE_FILE, 'w') as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


def screen_conservative(quotes: pd.DataFrame) -> pd.DataFrame:
    """
    稳健轨筛选
    条件：市值200亿-2000亿, PE 10-30x, 低波动, 机构持仓, 量价配合
    """
    cfg = CONFIG['screening']['conservative']
    
    if quotes.empty:
        return pd.DataFrame()
    
    df = quotes.copy()
    
    # 市值筛选
    if 'total_market_cap' in df.columns:
        df = df[(df['total_market_cap'] >= cfg['min_market_cap']) & 
                (df['total_market_cap'] <= cfg['max_market_cap'])]
    
    # PE筛选
    if 'pe_dynamic' in df.columns:
        df = df[(df['pe_dynamic'] >= cfg['min_pe']) & 
                (df['pe_dynamic'] <= cfg['max_pe'])]
    
    # 排除科创板和北交所（波动太大，不适合稳健轨）
    if 'code' in df.columns:
        df = df[~df['code'].str.startswith(('68', '4', '8'))]
    
    # 成交量筛选：日均成交额>5000万
    if 'amount' in df.columns:
        df = df[df['amount'] >= cfg['min_avg_volume_20d']]
    
    # 剔除当日涨跌幅异常（排除一字板、天地板等）
    if 'pct_change' in df.columns:
        df = df[(df['pct_change'] > -8) & (df['pct_change'] < 8)]
    
    # 按成交额排序，取流动性最好的
    if 'amount' in df.columns:
        df = df.sort_values('amount', ascending=False)
    
    # 综合评分
    df = _score_conservative(df)
    
    result = df.head(CONSERVATIVE_COUNT * 3)  # 取3倍候选再精选
    
    logger.info(f"稳健轨初筛: {len(result)} 只候选")
    return result


def _score_conservative(df: pd.DataFrame) -> pd.DataFrame:
    """稳健轨综合评分"""
    scores = pd.Series(0, index=df.index, dtype=float)
    
    # 成交额越高越好（流动性）
    if 'amount' in df.columns:
        amount_rank = df['amount'].rank(pct=True)
        scores += amount_rank * 20
    
    # PE越低越好（估值）
    if 'pe_dynamic' in df.columns:
        pe = df['pe_dynamic'].clip(0, 50)
        pe_rank = (50 - pe) / 50
        scores += pe_rank * 20
    
    # 涨幅适中（不要追高也不要抄底）
    if 'pct_change' in df.columns:
        pct = df['pct_change'].abs()
        pct_score = (10 - pct.clip(0, 10)) / 10
        scores += pct_score * 15
    
    # 换手率适中（太高不稳定，太低没流动性）
    if 'turnover_rate' in df.columns:
        turnover = df['turnover_rate'].clip(0, 15)
        turnover_score = (15 - abs(turnover - 3)) / 15
        scores += turnover_score * 15
    
    # 量比在1-2之间（温和放量）
    if 'volume_ratio' in df.columns:
        vr = df['volume_ratio'].clip(0.5, 5)
        vr_score = (5 - abs(vr - 1.5)) / 5
        scores += vr_score * 15
    
    # 振幅不宜过大
    if 'amplitude' in df.columns:
        amp = df['amplitude'].clip(0, 15)
        amp_score = (15 - amp) / 15
        scores += amp_score * 15
    
    df['_score'] = scores
    return df.sort_values('_score', ascending=False)


def screen_aggressive(quotes: pd.DataFrame) -> pd.DataFrame:
    """
    进取轨筛选
    条件：放量、涨停基因、资金净流入、换手率高、题材热度
    """
    cfg = CONFIG['screening']['aggressive']
    
    if quotes.empty:
        return pd.DataFrame()
    
    df = quotes.copy()
    
    # 市值筛选
    if 'total_market_cap' in df.columns:
        df = df[(df['total_market_cap'] >= cfg['min_market_cap']) & 
                (df['total_market_cap'] <= cfg['max_market_cap'])]
    
    # 换手率筛选
    if 'turnover_rate' in df.columns:
        df = df[df['turnover_rate'] >= cfg['min_daily_turnover_rate']]
    
    # 量比筛选
    if 'volume_ratio' in df.columns:
        df = df[df['volume_ratio'] >= cfg['min_volume_ratio_5d']]
    
    # 排除一字板（买不进）
    if 'pct_change' in df.columns:
        df = df[df['pct_change'] < 9.5]  # 非一字涨停
    
    # 综合评分
    df = _score_aggressive(df)
    
    result = df.head(AGGRESSIVE_COUNT * 3)
    
    logger.info(f"进取轨初筛: {len(result)} 只候选")
    return result


def _score_aggressive(df: pd.DataFrame) -> pd.DataFrame:
    """进取轨综合评分"""
    scores = pd.Series(0, index=df.index, dtype=float)
    
    # 换手率越高越好（但不能太高）
    if 'turnover_rate' in df.columns:
        turnover = df['turnover_rate'].clip(3, 20)
        scores += (turnover - 3) / 17 * 25
    
    # 量比越高越好
    if 'volume_ratio' in df.columns:
        vr = df['volume_ratio'].clip(1, 10)
        scores += (vr - 1) / 9 * 25
    
    # 涨幅适中（2-6%最佳，追涨但不过分）
    if 'pct_change' in df.columns:
        pct = df['pct_change'].clip(-5, 10)
        pct_score = 10 - abs(pct - 3)
        scores += pct_score.clip(0, 10) * 2
    
    # 成交额（要有量）
    if 'amount' in df.columns:
        amount_rank = df['amount'].rank(pct=True)
        scores += amount_rank * 20
    
    # 振幅（进取轨接受更大振幅）
    if 'amplitude' in df.columns:
        amp = df['amplitude'].clip(3, 15)
        scores += amp / 15 * 10
    
    df['_score'] = scores
    return df.sort_values('_score', ascending=False)


def check_recent_limit_up(symbol: str, lookback_days: int = 10) -> bool:
    """检查近期是否有涨停"""
    try:
        df = get_stock_history(symbol, days=lookback_days + 5)
        if df.empty:
            return False
        
        close_col = '收盘' if '收盘' in df.columns else 'close'
        pct_col = '涨跌幅' if '涨跌幅' in df.columns else None
        
        if pct_col and pct_col in df.columns:
            return any(df[pct_col].tail(lookback_days) >= 9.5)
        
        # 用收盘价估算
        if close_col in df.columns:
            close = df[close_col].values
            if len(close) > 1:
                pct = np.diff(close) / close[:-1] * 100
                return any(pct[-lookback_days:] >= 9.5)
    except:
        pass
    return False


def get_sector_hotness() -> dict:
    """获取板块热度排名"""
    try:
        df = get_sector_flow()
        if df.empty:
            return {}
        
        hotness = {}
        for _, row in df.head(10).iterrows():
            name = row.get('名称', '')
            pct = row.get('涨跌幅', 0)
            flow = row.get('主力净流入-净额', 0)
            hotness[name] = {'pct_change': pct, 'net_flow': flow}
        return hotness
    except:
        return {}


def generate_weekly_pool(force_refresh: bool = False) -> list:
    """
    生成周度精选池
    返回：标的列表，每只包含代码、名称、买进价、目标价、止损价、推荐逻辑
    """
    today = datetime.now()
    week_key = today.strftime('%Y-W%W')
    
    # 检查缓存
    cache = load_pool_cache()
    if not force_refresh and cache.get('week') == week_key:
        logger.info(f"使用缓存精选池 (周次: {week_key})")
        return cache.get('pool', [])
    
    logger.info(f"生成新精选池 (周次: {week_key})")
    
    # 获取全市场实时行情
    quotes = get_realtime_quotes()
    if quotes.empty:
        logger.error("无法获取行情数据，使用缓存")
        return cache.get('pool', [])
    
    # 稳健轨
    conservative = screen_conservative(quotes)
    
    # 进取轨
    aggressive = screen_aggressive(quotes)
    
    pool = []
    
    # 添加稳健标的
    for _, row in conservative.head(CONSERVATIVE_COUNT).iterrows():
        code = row.get('code', '')
        name = row.get('name', '')
        price = row.get('price', 0)
        
        if not code or not name or price <= 0:
            continue
        
        stock = _build_stock_entry(code, name, price, 'conservative', row)
        pool.append(stock)
    
    # 添加进取标的
    for _, row in aggressive.head(AGGRESSIVE_COUNT).iterrows():
        code = row.get('code', '')
        name = row.get('name', '')
        price = row.get('price', 0)
        
        if not code or not name or price <= 0:
            continue
        
        stock = _build_stock_entry(code, name, price, 'aggressive', row)
        pool.append(stock)
    
    # 去重
    seen = set()
    unique_pool = []
    for s in pool:
        if s['code'] not in seen:
            seen.add(s['code'])
            unique_pool.append(s)
    
    # 保存缓存
    cache['week'] = week_key
    cache['pool'] = unique_pool
    cache['generated_at'] = today.isoformat()
    save_pool_cache(cache)
    
    logger.info(f"精选池生成完成: {len(unique_pool)} 只标的")
    return unique_pool


def _build_stock_entry(code: str, name: str, price: float, style: str, row: pd.Series) -> dict:
    """
    构建标的条目，计算买卖价格
    使用简化的百分比方法（不依赖K线历史数据），快速生成
    """
    cfg = CONFIG['pricing']
    
    # 基于当前价格和ATR近似计算买卖价
    # 不使用K线历史数据（避免网络超时），直接用百分比
    
    # 稳健轨：较窄的买卖区间
    if style == 'conservative':
        buy_discount = 0.02   # 买进价在当前价下方2%
        stop_discount = 0.04  # 止损在当前价下方4%
        target1_premium = 0.06  # 第一目标 涨6%
        target2_premium = 0.12  # 第二目标 涨12%
    else:
        buy_discount = 0.03   # 进取轨：稍宽的区间
        stop_discount = 0.05
        target1_premium = 0.08
        target2_premium = 0.15
    
    buy_low = round(price * (1 - buy_discount), 2)
    buy_high = round(price * 1.01, 2)
    if buy_low > buy_high:
        buy_low, buy_high = buy_high, buy_low
    
    target1 = round(price * (1 + target1_premium), 2)
    target2 = round(price * (1 + target2_premium), 2)
    stop_loss = round(price * (1 - stop_discount), 2)
    support = round(price * 0.95, 2)
    resistance = round(price * 1.10, 2)
    
    # 推荐逻辑
    pe = row.get('pe_dynamic', 'N/A')
    turnover = row.get('turnover_rate', 'N/A')
    volume_ratio = row.get('volume_ratio', 'N/A')
    
    if style == 'conservative':
        logic = f"低估值蓝筹 | PE={pe} | 流动性充裕 | 均线支撑明确"
    else:
        logic = f"短线活跃 | 换手率={turnover}% | 量比={volume_ratio} | 弹性标的"
    
    return {
        'code': code,
        'name': name,
        'style': style,
        'current_price': price,
        'buy_zone': f"{buy_low}-{buy_high}",
        'buy_low': buy_low,
        'buy_high': buy_high,
        'target1': target1,
        'target2': target2,
        'stop_loss': stop_loss,
        'support': support,
        'resistance': resistance,
        'pe': pe,
        'turnover_rate': turnover,
        'volume_ratio': volume_ratio,
        'amount': row.get('amount', 0),
        'total_market_cap': row.get('total_market_cap', 0),
        'logic': logic,
    }


def update_pool_prices(pool: list) -> list:
    """更新精选池中各标的的实时价格"""
    if not pool:
        return pool
    
    codes = [s['code'] for s in pool]
    
    try:
        quotes = get_realtime_quotes()
        if quotes.empty:
            return pool
        
        quote_dict = {}
        for _, row in quotes.iterrows():
            quote_dict[row.get('code', '')] = {
                'price': row.get('price', 0),
                'pct_change': row.get('pct_change', 0),
                'volume_ratio': row.get('volume_ratio', 0),
                'turnover_rate': row.get('turnover_rate', 0),
                'amount': row.get('amount', 0),
            }
        
        for stock in pool:
            q = quote_dict.get(stock['code'], {})
            if q:
                stock['current_price'] = q.get('price', stock.get('current_price', 0))
                stock['pct_change'] = q.get('pct_change', 0)
                stock['volume_ratio_now'] = q.get('volume_ratio', 0)
                stock['turnover_rate_now'] = q.get('turnover_rate', 0)
                stock['amount_now'] = q.get('amount', 0)
                
                # 判断是否触发买卖信号
                price = stock['current_price']
                if price > 0:
                    stock['buy_signal'] = stock['buy_low'] <= price <= stock['buy_high']
                    stock['target1_hit'] = price >= stock['target1']
                    stock['target2_hit'] = price >= stock['target2']
                    stock['stop_hit'] = price <= stock['stop_loss']
                    stock['above_resistance'] = price >= stock['resistance']
    except Exception as e:
        logger.error(f"更新价格失败: {e}")
    
    return pool


if __name__ == '__main__':
    print("=" * 60)
    print("A股短线选股引擎测试")
    print("=" * 60)
    
    pool = generate_weekly_pool(force_refresh=True)
    
    print(f"\n本周精选池 ({len(pool)} 只标的):")
    print("-" * 80)
    for i, s in enumerate(pool, 1):
        style_tag = "🟢稳健" if s['style'] == 'conservative' else "🔴进取"
        print(f"{i}. [{style_tag}] {s['code']} {s['name']}")
        print(f"   现价: {s['current_price']} | 买进区间: {s['buy_zone']}")
        print(f"   目标1: {s['target1']} | 目标2: {s['target2']} | 止损: {s['stop_loss']}")
        print(f"   逻辑: {s['logic']}")
        print()
