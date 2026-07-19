"""
A股短线跟踪系统 — 市场数据获取模块 v2
数据源：腾讯财经HTTP接口（主要）+ AKShare（备用）
腾讯接口已验证可用，延迟低、无需认证
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import logging
import yaml
import os
import json
import re
import requests
from io import StringIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

MAX_RETRIES = CONFIG['data_sources']['max_retries']
RETRY_DELAY = CONFIG['data_sources']['retry_delay']

# 腾讯财经接口
TENCENT_QT_URL = "https://qt.gtimg.cn/q="

# 股票代码格式映射：纯数字 -> 腾讯格式
def _to_tencent_code(code: str) -> str:
    """转换股票代码为腾讯格式"""
    code = str(code).strip()
    if code.startswith(('sh', 'sz')):
        return code
    if code.startswith(('6', '9')):
        return f"sh{code}"
    elif code.startswith(('0', '3', '2')):
        return f"sz{code}"
    elif code.startswith(('4', '8')):
        return f"bj{code}"
    return f"sz{code}"  # 默认深市


def _parse_tencent_quote(raw: str) -> dict:
    """解析腾讯财经单只股票行情数据"""
    try:
        # 提取引号内数据
        match = re.search(r'="(.*)"', raw)
        if not match:
            return {}
        data = match.group(1).split('~')
        if len(data) < 40:
            return {}
        
        return {
            'code': data[2],
            'name': data[1],
            'price': float(data[3]) if data[3] else 0,
            'prev_close': float(data[4]) if data[4] else 0,
            'open': float(data[5]) if data[5] else 0,
            'volume': int(data[6]) if data[6] else 0,  # 手
            'buy_volume': int(data[7]) if data[7] else 0,
            'sell_volume': int(data[8]) if data[8] else 0,
            'high': float(data[33]) if len(data) > 33 and data[33] else 0,
            'low': float(data[34]) if len(data) > 34 and data[34] else 0,
            'amount': float(data[37]) if len(data) > 37 and data[37] else 0,  # 万元
            'turnover_rate': float(data[38]) if len(data) > 38 and data[38] else 0,
            'pe_dynamic': float(data[39]) if len(data) > 39 and data[39] else 0,
            'amplitude': float(data[43]) if len(data) > 43 and data[43] else 0,
            'float_market_cap': float(data[44]) if len(data) > 44 and data[44] else 0,  # 流通市值（亿）
            'total_market_cap': float(data[45]) if len(data) > 45 and data[45] else 0,  # 总市值（亿）
            'pb': float(data[46]) if len(data) > 46 and data[46] else 0,
            'volume_ratio': float(data[49]) if len(data) > 49 and data[49] else 0,
        }
    except Exception as e:
        logger.warning(f"解析行情数据失败: {e}")
        return {}


def _fetch_tencent_batch(codes: list) -> list:
    """批量获取腾讯财经行情"""
    tencent_codes = [_to_tencent_code(c) for c in codes]
    url = TENCENT_QT_URL + ",".join(tencent_codes)
    
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = 'gbk'
        text = resp.text
        
        results = []
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line or '=' not in line:
                continue
            parsed = _parse_tencent_quote(line)
            if parsed:
                results.append(parsed)
        return results
    except Exception as e:
        logger.warning(f"腾讯接口请求失败: {e}")
        return []


def get_realtime_quotes(codes: list = None) -> pd.DataFrame:
    """
    获取A股实时行情
    如果指定 codes，只获取这些代码的行情（更快）
    否则获取预设的重点股票池行情
    """
    logger.info("获取A股实时行情（腾讯接口）...")
    
    if codes is None:
        # 预设重点股票池：沪深300 + 中证500 + 创业板50 代表性标的
        # 实际部署时这里会通过指数成分股接口获取完整列表
        # 这里先放一个较大范围的基础池
        codes = _get_default_stock_pool()
    
    all_results = []
    batch_size = 50  # 腾讯接口单次最多约50只
    
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        results = _fetch_tencent_batch(batch)
        all_results.extend(results)
        if i + batch_size < len(codes):
            time.sleep(0.5)  # 批次间短暂延迟
    
    if not all_results:
        logger.warning("腾讯接口未返回数据，尝试AKShare备用...")
        return _fallback_akshare_quotes()
    
    df = pd.DataFrame(all_results)
    
    # 计算涨跌幅
    if 'price' in df.columns and 'prev_close' in df.columns:
        df['pct_change'] = np.where(
            df['prev_close'] > 0,
            (df['price'] - df['prev_close']) / df['prev_close'] * 100,
            0
        )
    
    # 过滤：排除ST、退市等
    if 'name' in df.columns:
        df = df[~df['name'].str.contains('ST|退市', na=False)]
    
    # 市值单位转换为元
    if 'total_market_cap' in df.columns:
        df['total_market_cap'] = df['total_market_cap'] * 1e8
    if 'float_market_cap' in df.columns:
        df['float_market_cap'] = df['float_market_cap'] * 1e8
    if 'amount' in df.columns:
        df['amount'] = df['amount'] * 10000  # 万元->元
    
    logger.info(f"获取到 {len(df)} 只股票实时行情")
    return df


def _fallback_akshare_quotes() -> pd.DataFrame:
    """AKShare备用数据源"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            column_mapping = {
                '代码': 'code', '名称': 'name', '最新价': 'price',
                '涨跌幅': 'pct_change', '涨跌额': 'change', '成交量': 'volume',
                '成交额': 'amount', '振幅': 'amplitude', '最高': 'high',
                '最低': 'low', '今开': 'open', '昨收': 'prev_close',
                '量比': 'volume_ratio', '换手率': 'turnover_rate',
                '市盈率-动态': 'pe_dynamic', '市净率': 'pb',
                '总市值': 'total_market_cap', '流通市值': 'float_market_cap',
            }
            existing = {k: v for k, v in column_mapping.items() if k in df.columns}
            df = df.rename(columns=existing)
            if 'name' in df.columns:
                df = df[~df['name'].str.contains('ST|退市|N ', na=False)]
            logger.info(f"AKShare备用获取到 {len(df)} 只股票")
            return df
    except Exception as e:
        logger.error(f"AKShare备用也失败: {e}")
    return pd.DataFrame()


def get_stock_history(symbol: str, period: str = "daily", days: int = 60) -> pd.DataFrame:
    """
    获取个股历史K线数据
    快速模式：不实际获取历史K线，返回空DataFrame
    由 price_model 使用简化百分比方法计算买卖价
    
    如需真实K线数据，可安装 baostock 并在网络环境允许时启用
    """
    logger.info(f"获取 {symbol} 历史K线 — 快速模式（跳过）")
    # 在沙箱环境中网络受限，直接返回空DataFrame
    # price_model 会使用简化的百分比方法
    return pd.DataFrame()


def _to_baostock_code(code: str) -> str:
    """转换代码为 Baostock 格式"""
    code = str(code).strip().zfill(6)
    if code.startswith(('6', '9')):
        return f"sh.{code}"
    return f"sz.{code}"


def _generate_synthetic_history(symbol: str, days: int) -> pd.DataFrame:
    """
    基于当前行情生成模拟历史K线（降级方案）
    使用随机游走 + 当前价作为锚点
    仅在所有数据源都不可用时使用，会在报告中标注 [ESTIMATED]
    """
    try:
        # 获取当前价格
        quotes = get_realtime_quotes(codes=[symbol])
        if quotes.empty:
            return pd.DataFrame()
        
        current = quotes.iloc[0]
        price = current['price']
        prev_close = current.get('prev_close', price)
        
        np.random.seed(hash(symbol) % 2**31)
        
        # 基于日波动率生成模拟K线
        daily_vol = 0.02  # 默认2%日波动
        prices = [prev_close]
        
        for i in range(days):
            ret = np.random.normal(0.0005, daily_vol)  # 微偏正
            new_price = prices[-1] * (1 + ret)
            prices.append(new_price)
        
        # 调整使最后价格等于当前价
        prices = np.array(prices)
        ratio = price / prices[-1]
        prices = prices * (1 + (ratio - 1) * np.linspace(0, 1, len(prices)))
        
        rows = []
        for i in range(1, len(prices)):
            p = prices[i]
            prev_p = prices[i-1]
            rows.append({
                'date': (datetime.now() - timedelta(days=len(prices)-1-i)).strftime('%Y-%m-%d'),
                'open': round(prev_p, 2),
                'high': round(max(p, prev_p) * (1 + np.random.uniform(0, 0.01)), 2),
                'low': round(min(p, prev_p) * (1 - np.random.uniform(0, 0.01)), 2),
                'close': round(p, 2),
                'volume': int(current.get('volume', 100000) * np.random.uniform(0.5, 1.5)),
            })
        
        return pd.DataFrame(rows)
    except Exception as e:
        logger.error(f"模拟K线生成失败: {e}")
        return pd.DataFrame()


def get_market_index() -> dict:
    """
    获取主要指数行情（腾讯接口）
    """
    logger.info("获取主要指数行情...")
    
    index_codes = {
        'sh000001': '上证指数',
        'sz399001': '深证成指',
        'sz399006': '创业板指',
        'sh000688': '科创50',
        'sh000300': '沪深300',
        'sh000905': '中证500',
    }
    
    try:
        results = _fetch_tencent_batch(list(index_codes.keys()))
        result = {}
        for item in results:
            name = index_codes.get(f"sh{item['code']}", index_codes.get(f"sz{item['code']}", item.get('name', '')))
            pct = ((item['price'] - item['prev_close']) / item['prev_close'] * 100) if item['prev_close'] > 0 else 0
            result[name] = {
                'price': item['price'],
                'pct_change': round(pct, 2),
                'volume': item['volume'],
                'amount': item['amount'],
            }
        return result
    except Exception as e:
        logger.warning(f"指数行情获取失败: {e}")
    return {}


def get_sector_flow() -> pd.DataFrame:
    """
    获取板块资金流向排名
    腾讯接口不直接支持，使用WebSearch或返回空
    """
    # 腾讯接口对板块数据支持有限，返回空DataFrame
    # 板块热度会在 stock_screener 中通过其他方式获取
    logger.info("板块资金流向数据（当前版本通过WebSearch获取）")
    return pd.DataFrame()


def get_dragon_tiger_board() -> pd.DataFrame:
    """获取龙虎榜数据"""
    logger.info("龙虎榜数据获取（当前版本暂不支持）")
    return pd.DataFrame()


def get_limit_up_down_stats() -> dict:
    """获取涨跌停统计"""
    # 从腾讯实时行情中统计
    try:
        quotes = get_realtime_quotes()
        if quotes.empty:
            return {'limit_up_count': 0, 'limit_up_stocks': []}
        
        limit_up = quotes[quotes['pct_change'] >= 9.5]
        return {
            'limit_up_count': len(limit_up),
            'limit_up_stocks': limit_up[['code', 'name', 'price', 'pct_change']].head(20).to_dict('records')
        }
    except:
        return {'limit_up_count': 0, 'limit_up_stocks': []}


def get_stock_financial_brief(symbol: str) -> dict:
    """获取个股财务简要数据"""
    # 腾讯接口不提供财务数据
    return {}


def get_pool_stocks_realtime(codes: list) -> pd.DataFrame:
    """获取精选池标的的实时行情"""
    return get_realtime_quotes(codes=codes)


def _get_default_stock_pool() -> list:
    """
    获取默认股票池（A股主要标的）
    包含沪深300核心标的 + 活跃中小盘
    这是无法获取全市场数据时的降级方案
    """
    # 沪深300核心蓝筹
    shanghai_50 = [
        '600519', '600036', '601318', '600276', '600887', '600900', '601166',
        '601398', '600030', '601012', '600809', '600585', '600690', '601888',
        '600031', '600048', '601668', '600104', '600028', '601857',
        '600050', '601899', '600406', '601088', '600436', '600309',
        '603259', '600009', '601225', '600438', '600745', '600570',
        '601628', '601601', '600000', '600016', '601336', '601211',
        '601390', '600919', '600346', '600660', '600989', '600019',
    ]
    
    shenzhen_core = [
        '000001', '000002', '000858', '000333', '000651', '000725', '000568',
        '000063', '002415', '002475', '000338', '002142', '002594',
        '002230', '000792', '002352', '002714', '000625', '002459',
        '000100', '002271', '002304', '002241', '000876', '002027',
        '002460', '002709', '002371', '002049', '002129', '000301',
        '000157', '002179', '002202', '000538',
    ]
    
    gem_active = [
        '300750', '300059', '300124', '300274', '300015', '300498',
        '300760', '300122', '300413', '300502', '300394', '300308',
        '300033', '300347', '300285', '300573', '300454', '300676',
        '300782', '300661', '300763', '300014', '300450', '300476',
        '300408', '300529', '300316', '300251', '300699', '300628',
    ]
    
    science_board = [
        '688981', '688012', '688036', '688111', '688008', '688396',
        '688005', '688009', '688126', '688185', '688256', '688303',
        '688065', '688599', '688029', '688180', '688088', '688561',
        '688187', '688169',
    ]
    
    all_codes = shanghai_50 + shenzhen_core + gem_active + science_board
    return list(set(all_codes))  # 去重


def is_trading_day() -> bool:
    """判断今天是否为A股交易日"""
    today = datetime.now()
    if today.weekday() >= 5:
        return False
    
    # 尝试获取行情确认
    try:
        result = _fetch_tencent_batch(['sh000001'])
        if result:
            return True
    except:
        pass
    
    # 退而求其次：工作日假设为交易日
    return today.weekday() < 5


def is_market_open() -> bool:
    """判断当前是否在交易时段"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    
    morning_session = (hour == 9 and minute >= 30) or (hour == 10) or (hour == 11 and minute <= 30)
    afternoon_session = (hour == 13) or (hour == 14) or (hour == 15 and minute == 0)
    
    return is_trading_day() and (morning_session or afternoon_session)


def get_overnight_news() -> str:
    """
    获取隔夜要闻摘要
    通过WebSearch获取最新市场动态
    """
    # 这个函数会在 main.py 中通过 WebSearch 实现
    # 这里返回空，由调用方处理
    return ''


if __name__ == '__main__':
    print("="*60)
    print("市场数据模块测试（腾讯接口）")
    print("="*60)
    
    print("\n=== 实时行情测试 ===")
    quotes = get_realtime_quotes()
    if not quotes.empty:
        print(f"获取成功: {len(quotes)} 只股票")
        print(quotes[['code', 'name', 'price', 'pct_change']].head(10))
    else:
        print("获取失败")
    
    print("\n=== 指数行情测试 ===")
    indices = get_market_index()
    for name, data in indices.items():
        print(f"  {name}: {data['price']} ({data['pct_change']:+.2f}%)")
    
    print("\n=== 历史K线测试 ===")
    hist = get_stock_history('000001', days=10)
    if not hist.empty:
        print(hist.tail(5))
    
    print(f"\n=== 是否交易日: {is_trading_day()} ===")
    print(f"=== 是否交易时段: {is_market_open()} ===")
