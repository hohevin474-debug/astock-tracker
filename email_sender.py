"""
A股短线跟踪系统 — 推送模块
由于沙箱环境网络限制，采用本地报告 + Web预览方式
支持：本地HTML报告、Web预览、AgentMail（可选）
"""
import os
import json
import logging
import yaml
from datetime import datetime
import shutil

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), 'public')


def save_report(html_content: str, report_type: str) -> str:
    """
    保存报告到本地文件系统
    
    Args:
        html_content: HTML格式报告
        report_type: 报告类型 (pre_market, intraday_1, midday, intraday_3, close)
    
    Returns:
        报告文件路径
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 保存历史报告
    filename = f"{timestamp}_{report_type}.html"
    filepath = os.path.join(REPORTS_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # 更新最新报告
    latest_path = os.path.join(REPORTS_DIR, f'latest_{report_type}.html')
    with open(latest_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # 复制到 public 目录（用于Web预览）
    public_path = os.path.join(PUBLIC_DIR, f'{report_type}.html')
    shutil.copy(latest_path, public_path)
    
    # 更新首页索引
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


def send_report(to_email: str, subject: str, html_content: str, 
                plain_text: str = '') -> bool:
    """
    发送报告（本地保存 + AgentMail备用）
    """
    # 始终保存到本地
    report_type = 'custom'
    if '盘前' in subject:
        report_type = 'pre_market'
    elif '午间' in subject:
        report_type = 'midday'
    elif '收盘' in subject:
        report_type = 'close'
    elif '盘中更新#1' in subject:
        report_type = 'intraday_1'
    elif '盘中更新#3' in subject:
        report_type = 'intraday_3'
    
    save_report(html_content, report_type)
    
    # 尝试 AgentMail（如果可用）
    try:
        inbox_config_file = os.path.join(os.path.dirname(__file__), '.inbox_config.json')
        if os.path.exists(inbox_config_file):
            with open(inbox_config_file, 'r') as f:
                cfg = json.load(f)
            
            from agentmail import AgentMail
            client = AgentMail(api_key=cfg.get('api_key', ''))
            client.inboxes.messages.send(
                inbox_id=cfg['inbox_id'],
                to=to_email,
                subject=subject,
                html=html_content,
            )
            logger.info(f"AgentMail发送成功: {subject}")
            return True
    except Exception as e:
        logger.warning(f"AgentMail发送失败（报告已保存到本地）: {e}")
    
    return True  # 本地保存成功即视为成功


def get_latest_report_url(report_type: str = 'pre_market') -> str:
    """获取最新报告的Web预览URL"""
    return f"/public/{report_type}.html"


def get_report_index_url() -> str:
    """获取报告中心首页URL"""
    return "/public/index.html"


if __name__ == '__main__':
    # 初始化 public 目录
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    _update_index_html()
    print(f"报告中心已初始化: {PUBLIC_DIR}/index.html")
