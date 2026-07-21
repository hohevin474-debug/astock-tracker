"""
PDF 报告生成器
将 HTML 报告转换为 PDF，保存到 /workspace 用户可见目录
"""
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

PDF_OUTPUT_DIR = '/workspace/stock-tracker/pdfs'
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)


def generate_pdf(html_content: str, report_type: str, pool: list = None, indices: dict = None) -> str:
    """
    将 HTML 报告转为 PDF 文件
    
    Args:
        html_content: HTML 格式的报告内容
        report_type: 报告类型（pre_market, intraday_1, midday, intraday_3, close, track）
        pool: 精选池数据（用于生成纯文本摘要）
        indices: 指数数据
    
    Returns:
        PDF 文件路径
    """
    try:
        from weasyprint import HTML
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{report_type}.pdf"
        filepath = os.path.join(PDF_OUTPUT_DIR, filename)
        
        # 用 weasyprint 将 HTML 转为 PDF
        HTML(string=html_content).write_pdf(filepath)
        
        # 也保存最新版本（方便快速查看）
        latest_path = os.path.join(PDF_OUTPUT_DIR, f'latest_{report_type}.pdf')
        import shutil
        shutil.copy(filepath, latest_path)
        
        logger.info(f"PDF 已生成: {filepath}")
        return filepath
    
    except ImportError:
        logger.warning("weasyprint 未安装，尝试安装...")
        _install_weasyprint()
        return generate_pdf(html_content, report_type, pool, indices)
    
    except Exception as e:
        logger.error(f"PDF 生成失败: {e}，尝试备用方案...")
        return _generate_simple_pdf(html_content, report_type, pool, indices)


def _install_weasyprint():
    """安装 weasyprint"""
    import subprocess
    try:
        subprocess.run(['sudo', 'pip3', 'install', 'weasyprint'], check=True, capture_output=True)
        logger.info("weasyprint 安装成功")
    except Exception as e:
        logger.error(f"weasyprint 安装失败: {e}")


def _generate_simple_pdf(html_content: str, report_type: str, pool=None, indices=None) -> str:
    """
    备用方案：用 fpdf2 生成简单 PDF
    """
    try:
        from fpdf import FPDF
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{report_type}.pdf"
        filepath = os.path.join(PDF_OUTPUT_DIR, filename)
        
        pdf = FPDF()
        pdf.add_page()
        
        # 注册中文字体
        font_paths = [
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        ]
        font_loaded = False
        for fp in font_paths:
            if os.path.exists(fp):
                pdf.add_font('Chinese', '', fp, uni=True)
                pdf.add_font('Chinese', 'B', fp, uni=True)
                font_loaded = True
                break
        
        if not font_loaded:
            # 尝试安装中文字体
            import subprocess
            subprocess.run(['apt-get', 'install', '-y', 'fonts-wqy-zenhei'], 
                          capture_output=True, timeout=30)
            for fp in font_paths:
                if os.path.exists(fp):
                    pdf.add_font('Chinese', '', fp, uni=True)
                    pdf.add_font('Chinese', 'B', fp, uni=True)
                    font_loaded = True
                    break
        
        if font_loaded:
            pdf.set_font('Chinese', 'B', 16)
        else:
            pdf.set_font('Helvetica', 'B', 16)
        
        # 标题
        report_names = {
            'pre_market': '盘前精选推送',
            'intraday_1': '盘中更新#1',
            'midday': '午间复盘',
            'intraday_3': '盘中更新#3',
            'close': '收盘总结',
            'track': '持仓跟踪',
        }
        title = f"A股短线跟踪 - {report_names.get(report_type, report_type)}"
        pdf.cell(0, 10, title, ln=True, align='C')
        
        # 日期
        pdf.set_font('Chinese', '', 10) if font_loaded else pdf.set_font('Helvetica', '', 10)
        now = datetime.now()
        pdf.cell(0, 8, now.strftime('%Y年%m月%d日 %H:%M'), ln=True, align='C')
        pdf.ln(5)
        
        # 指数概览
        if indices:
            pdf.set_font('Chinese', 'B', 12) if font_loaded else pdf.set_font('Helvetica', 'B', 12)
            pdf.cell(0, 8, '主要指数', ln=True)
            pdf.set_font('Chinese', '', 9) if font_loaded else pdf.set_font('Helvetica', '', 9)
            
            for name in ['上证指数', '深证成指', '创业板指', '沪深300']:
                data = indices.get(name, {})
                if data:
                    pct = data.get('pct_change', 0)
                    sign = '+' if pct > 0 else ''
                    pdf.cell(0, 6, f"  {name}: {data['price']:.0f}  ({sign}{pct:.2f}%)", ln=True)
            pdf.ln(3)
        
        # 精选池表格
        if pool:
            pdf.set_font('Chinese', 'B', 12) if font_loaded else pdf.set_font('Helvetica', 'B', 12)
            pdf.cell(0, 8, '本周精选池', ln=True)
            pdf.ln(2)
            
            # 表头
            pdf.set_font('Chinese', 'B', 8) if font_loaded else pdf.set_font('Helvetica', 'B', 8)
            pdf.cell(20, 6, '代码', 1)
            pdf.cell(28, 6, '名称', 1)
            pdf.cell(18, 6, '风格', 1)
            pdf.cell(20, 6, '现价', 1)
            pdf.cell(32, 6, '买进区间', 1)
            pdf.cell(20, 6, '目标1', 1)
            pdf.cell(20, 6, '目标2', 1)
            pdf.cell(20, 6, '止损', 1)
            pdf.ln()
            
            pdf.set_font('Chinese', '', 8) if font_loaded else pdf.set_font('Helvetica', '', 8)
            for s in pool:
                style = '稳健' if s.get('style') == 'conservative' else '进取'
                pdf.cell(20, 6, s.get('code', ''), 1)
                pdf.cell(28, 6, s.get('name', '')[:4], 1)
                pdf.cell(18, 6, style, 1)
                pdf.cell(20, 6, str(s.get('current_price', '')), 1)
                buy_range = f"{s.get('buy_low','')}-{s.get('buy_high','')}"
                pdf.cell(32, 6, buy_range, 1)
                pdf.cell(20, 6, str(s.get('target1', '')), 1)
                pdf.cell(20, 6, str(s.get('target2', '')), 1)
                pdf.cell(20, 6, str(s.get('stop_loss', '')), 1)
                pdf.ln()
        
        # 免责声明
        pdf.ln(5)
        pdf.set_font('Chinese', '', 7) if font_loaded else pdf.set_font('Helvetica', '', 7)
        pdf.multi_cell(0, 4, '免责声明：本报告由AI自动生成，仅供参考，不构成个人投资建议。股市有风险，投资需谨慎。')
        
        pdf.output(filepath)
        
        # 最新版本
        latest_path = os.path.join(PDF_OUTPUT_DIR, f'latest_{report_type}.pdf')
        import shutil
        shutil.copy(filepath, latest_path)
        
        logger.info(f"PDF (fpdf2) 已生成: {filepath}")
        return filepath
        
    except Exception as e:
        logger.error(f"备用 PDF 生成也失败: {e}")
        return ''


def build_text_summary(pool: list, indices: dict, report_type: str) -> str:
    """
    生成纯文本摘要，用于在 WorkBuddy 聊天框展示
    """
    now = datetime.now()
    weekday_map = ['一','二','三','四','五','六','日']
    weekday = weekday_map[now.weekday()]
    
    report_names = {
        'pre_market': f'📊 盘前精选推送 · 周{weekday}',
        'intraday_1': f'📈 盘中更新#1 · 周{weekday} 10:30',
        'midday': f'🕐 午间复盘 · 周{weekday} 11:30',
        'intraday_3': f'📈 盘中更新#3 · 周{weekday} 14:00',
        'close': f'🔔 收盘总结 · 周{weekday} 15:00',
        'track': f'📋 持仓跟踪 · 周{weekday}',
    }
    
    lines = []
    lines.append("=" * 55)
    lines.append(f"  {report_names.get(report_type, report_type)}")
    lines.append(f"  {now.strftime('%Y年%m月%d日 %H:%M')}")
    lines.append("=" * 55)
    
    # 指数
    if indices:
        lines.append("")
        lines.append("📈 主要指数")
        lines.append("-" * 55)
        for name in ['上证指数', '深证成指', '创业板指', '科创50', '沪深300', '中证500']:
            data = indices.get(name, {})
            if data:
                pct = data.get('pct_change', 0)
                sign = '+' if pct > 0 else ''
                color = '🔴' if pct < -1 else ('🟢' if pct > 1 else '⚪')
                lines.append(f"  {color} {name:6s}  {data['price']:>10.2f}  ({sign}{pct:.2f}%)")
    
    # 精选池
    if pool:
        lines.append("")
        lines.append("🎯 精选池")
        lines.append("-" * 55)
        lines.append(f"  {'代码':<8s} {'名称':<8s} {'风格':<6s} {'现价':>8s} {'涨跌':>8s}  {'买进区间':<14s} {'目标1':>8s} {'止损':>8s}")
        lines.append("  " + "-" * 90)
        
        for s in pool:
            code = s.get('code', '')
            name = s.get('name', '')
            style = '🟢稳健' if s.get('style') == 'conservative' else '🔴进取'
            price = s.get('current_price', 0)
            pct = s.get('pct_change', 0)
            sign = '+' if pct > 0 else ''
            buy_low = s.get('buy_low', 0)
            buy_high = s.get('buy_high', 0)
            target1 = s.get('target1', 0)
            stop = s.get('stop_loss', 0)
            
            # 信号
            signal = ''
            if buy_low <= price <= buy_high:
                signal = ' 💰买进'
            elif price >= target1:
                signal = ' 🎯达标'
            elif price <= stop:
                signal = ' ⛔止损'
            
            lines.append(f"  {code:<8s} {name:<8s} {style:<6s} {price:>8.2f} {sign}{pct:>7.2f}%  {buy_low:.2f}-{buy_high:.2f}    {target1:>8.2f}  {stop:>8.2f}{signal}")
    
    lines.append("")
    lines.append("-" * 55)
    lines.append("⚠️ 本报告由AI自动生成，仅供参考，不构成个人投资建议。")
    lines.append("📱 完整PDF报告已保存至 /workspace/stock-tracker/pdfs/")
    
    return '\n'.join(lines)
