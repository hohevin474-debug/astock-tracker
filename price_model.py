"""
A股短线跟踪系统 — 定价模型
基于技术分析计算支撑位、阻力位、布林带、VWAP等
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import yaml
import os

from market_data import get_stock_history, get_realtime_quotes

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)


def calc_support_resistance(hist_df: pd.DataFrame) -> dict:
    """
    计算支撑位和阻力位
    基于历史高低点和均线系统
    """
    if hist_df.empty:
        return {}
    
    close_col = '收盘' if '收盘' in hist_df.columns else 'close'
    high_col = '最高' if '最高' in hist_df.columns else 'high'
    low_col = '最低' if '最低' in hist_df.columns else 'low'
    
    if close_col not in hist_df.columns:
        return {}
    
    closes = hist_df[close_col].values
    highs = hist_df[high_col].values if high_col in hist_df.columns else closes
    lows = hist_df[low_col].values if low_col in hist_df.columns else closes
    
    current = closes[-1]
    
    # 均线系统
    ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else current
    ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else current
    ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else current
    ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else current
    
    # 近期高低点
    low_10 = np.min(lows[-10:])
    low_20 = np.min(lows[-20:])
    high_10 = np.max(highs[-10:])
    high_20 = np.max(highs[-20:])
    high_60 = np.max(highs[-60:]) if len(highs) >= 60 else high_20
    
    # 综合支撑位（取近期低点和MA20中较高者）
    support_levels = sorted([low_10, low_20, ma20], reverse=True)
    # 综合阻力位（取近期高点和MA20中较低者）
    resistance_levels = sorted([high_10, high_20, high_60])
    
    return {
        'current_price': round(current, 2),
        'support_1': round(support_levels[0], 2),
        'support_2': round(support_levels[1], 2),
        'resistance_1': round(resistance_levels[0], 2),
        'resistance_2': round(resistance_levels[1], 2),
        'resistance_3': round(resistance_levels[2], 2) if len(resistance_levels) > 2 else round(resistance_levels[1], 2),
        'ma5': round(ma5, 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'ma60': round(ma60, 2),
    }


def calc_bollinger_bands(hist_df: pd.DataFrame, period: int = 20, std_dev: float = 2) -> dict:
    """
    计算布林带
    """
    if hist_df.empty:
        return {}
    
    close_col = '收盘' if '收盘' in hist_df.columns else 'close'
    if close_col not in hist_df.columns:
        return {}
    
    closes = hist_df[close_col].tail(period).values
    if len(closes) < period:
        return {}
    
    ma = np.mean(closes)
    std = np.std(closes)
    
    current = closes[-1]
    
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    bandwidth = (upper - lower) / ma * 100  # 带宽百分比
    position = (current - lower) / (upper - lower) * 100  # 价格在带中的位置
    
    return {
        'boll_upper': round(upper, 2),
        'boll_middle': round(ma, 2),
        'boll_lower': round(lower, 2),
        'bandwidth_pct': round(bandwidth, 2),
        'position_pct': round(position, 1),
    }


def calc_vwap(hist_df: pd.DataFrame) -> dict:
    """
    计算成交量加权均价（VWAP）
    用于判断当前价格在日内均价上方还是下方
    """
    if hist_df.empty:
        return {}
    
    # 尝试获取分时数据计算VWAP
    # 如果没有分时数据，用近期日线近似
    close_col = '收盘' if '收盘' in hist_df.columns else 'close'
    volume_col = '成交量' if '成交量' in hist_df.columns else 'volume'
    
    if close_col not in hist_df.columns or volume_col not in hist_df.columns:
        return {}
    
    recent = hist_df.tail(5)
    prices = recent[close_col].values
    volumes = recent[volume_col].values
    
    if volumes.sum() == 0:
        return {}
    
    vwap = np.average(prices, weights=volumes)
    current = prices[-1]
    
    return {
        'vwap_5d': round(vwap, 2),
        'price_vs_vwap': round((current - vwap) / vwap * 100, 2),
    }


def calc_atr(hist_df: pd.DataFrame, period: int = 14) -> float:
    """
    计算平均真实波幅（ATR），用于设置止损和仓位
    """
    if hist_df.empty or len(hist_df) < period + 1:
        return 0
    
    high_col = '最高' if '最高' in hist_df.columns else 'high'
    low_col = '最低' if '最低' in hist_df.columns else 'low'
    close_col = '收盘' if '收盘' in hist_df.columns else 'close'
    
    if high_col not in hist_df.columns or low_col not in hist_df.columns:
        return 0
    
    highs = hist_df[high_col].values
    lows = hist_df[low_col].values
    closes = hist_df[close_col].values
    
    tr_list = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    
    if not tr_list:
        return 0
    
    atr = np.mean(tr_list[-period:])
    return round(atr, 2)


def calc_volume_profile(hist_df: pd.DataFrame) -> dict:
    """
    成交量分析：量比趋势、放量/缩量判断
    """
    if hist_df.empty:
        return {}
    
    volume_col = '成交量' if '成交量' in hist_df.columns else 'volume'
    if volume_col not in hist_df.columns:
        return {}
    
    volumes = hist_df[volume_col].tail(20).values
    
    if len(volumes) < 5:
        return {}
    
    vol_ma5 = np.mean(volumes[-5:])
    vol_ma10 = np.mean(volumes[-10:]) if len(volumes) >= 10 else vol_ma5
    vol_ma20 = np.mean(volumes)
    
    today_vol = volumes[-1]
    vol_ratio_5 = today_vol / vol_ma5 if vol_ma5 > 0 else 1
    vol_ratio_20 = today_vol / vol_ma20 if vol_ma20 > 0 else 1
    
    # 量能趋势
    if vol_ma5 > vol_ma10 > vol_ma20:
        trend = "放量"
    elif vol_ma5 < vol_ma10 < vol_ma20:
        trend = "缩量"
    else:
        trend = "平稳"
    
    return {
        'today_volume': int(today_vol),
        'vol_ma5': int(vol_ma5),
        'vol_ma20': int(vol_ma20),
        'vol_ratio_5d': round(vol_ratio_5, 2),
        'vol_ratio_20d': round(vol_ratio_20, 2),
        'trend': trend,
    }


def calc_rsi(hist_df: pd.DataFrame, period: int = 14) -> float:
    """
    计算RSI指标
    """
    if hist_df.empty or len(hist_df) < period + 1:
        return 50
    
    close_col = '收盘' if '收盘' in hist_df.columns else 'close'
    if close_col not in hist_df.columns:
        return 50
    
    closes = hist_df[close_col].tail(period + 1).values
    deltas = np.diff(closes)
    
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 1)


def calc_macd(hist_df: pd.DataFrame) -> dict:
    """
    计算MACD指标
    """
    if hist_df.empty or len(hist_df) < 35:
        return {}
    
    close_col = '收盘' if '收盘' in hist_df.columns else 'close'
    if close_col not in hist_df.columns:
        return {}
    
    closes = hist_df[close_col].values
    
    # EMA
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
    
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    macd_bar = 2 * (dif - dea)
    
    return {
        'dif': round(dif[-1], 3),
        'dea': round(dea[-1], 3),
        'macd': round(macd_bar[-1], 3),
        'signal': '金叉' if dif[-1] > dea[-1] and dif[-2] <= dea[-2] else (
            '死叉' if dif[-1] < dea[-1] and dif[-2] >= dea[-2] else (
            '多头' if dif[-1] > dea[-1] else '空头'
        )),
    }


def get_stock_full_analysis(code: str) -> dict:
    """
    获取个股完整的技术分析
    """
    try:
        hist = get_stock_history(code, days=100)
        if hist.empty:
            return {'error': f'无法获取 {code} 历史数据'}
        
        sr = calc_support_resistance(hist)
        bb = calc_bollinger_bands(hist)
        vwap = calc_vwap(hist)
        atr = calc_atr(hist)
        vol = calc_volume_profile(hist)
        rsi = calc_rsi(hist)
        macd = calc_macd(hist)
        
        return {
            'code': code,
            **sr,
            **bb,
            **vwap,
            'atr': atr,
            **vol,
            'rsi': rsi,
            **macd,
        }
    except Exception as e:
        logger.error(f"技术分析失败 {code}: {e}")
        return {'error': str(e)}


def generate_buy_sell_prices(code: str, current_price: float) -> dict:
    """
    基于技术分析生成买卖价格建议
    """
    analysis = get_stock_full_analysis(code)
    
    if 'error' in analysis:
        # 回退：基于当前价的百分比计算
        return {
            'buy_zone': f"{round(current_price * 0.97, 2)}-{round(current_price * 1.01, 2)}",
            'target_1': round(current_price * 1.08, 2),
            'target_2': round(current_price * 1.15, 2),
            'stop_loss': round(current_price * 0.95, 2),
            'risk_reward': '1:1.6',
            'method': 'default_pct',
        }
    
    support = analysis.get('support_1', current_price * 0.95)
    resistance = analysis.get('resistance_1', current_price * 1.08)
    atr = analysis.get('atr', current_price * 0.02)
    rsi = analysis.get('rsi', 50)
    
    # 根据RSI调整
    if rsi > 70:
        # 超买：降低买进价，提高止损
        buy_low = round(support, 2)
        buy_high = round(min(support * 1.02, current_price * 0.99), 2)
    elif rsi < 30:
        # 超卖：可以积极买进
        buy_low = round(support, 2)
        buy_high = round(min(support * 1.03, current_price * 1.01), 2)
    else:
        buy_low = round(max(support, current_price * 0.97), 2)
        buy_high = round(min(support * 1.03, current_price * 1.02), 2)
    
    if buy_low > buy_high:
        buy_low, buy_high = buy_high, buy_low
    
    target_1 = round(current_price * 1.08, 2)
    target_2 = round(max(resistance, current_price * 1.15), 2)
    stop_loss = round(min(support * 0.97, current_price * (1 - atr/current_price * 2)), 2)
    
    # 风险收益比
    risk = current_price - stop_loss
    reward = target_1 - current_price
    rr_ratio = f"1:{round(reward/risk, 1)}" if risk > 0 else "N/A"
    
    return {
        'buy_zone': f"{buy_low}-{buy_high}",
        'target_1': target_1,
        'target_2': target_2,
        'stop_loss': stop_loss,
        'risk_reward': rr_ratio,
        'method': 'technical',
        'rsi': rsi,
        'atr': atr,
        'bollinger_position': analysis.get('position_pct', 'N/A'),
    }


if __name__ == '__main__':
    # 测试
    test_codes = ['000001', '600519', '300750']
    for code in test_codes:
        print(f"\n{'='*50}")
        print(f"技术分析: {code}")
        print(f"{'='*50}")
        analysis = get_stock_full_analysis(code)
        for k, v in analysis.items():
            print(f"  {k}: {v}")
