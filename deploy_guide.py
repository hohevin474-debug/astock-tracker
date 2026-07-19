#!/usr/bin/env python3
"""
A股短线跟踪系统 — 独立运行脚本
可在任何有 Python 3.11+ 的机器上运行，不依赖 CodeBuddy 沙箱

部署方式：
1. 复制整个 stock-tracker 目录到你的服务器/电脑
2. pip install requests pyyaml pandas numpy
3. 配置 Bark Device Key: echo "jNVNkxWwVd88vNYoq7RxMa" > .bark_key
4. 设置 crontab（Linux/Mac）或 计划任务（Windows）

Linux/Mac crontab 配置（复制粘贴到终端）:
  crontab -e
  然后添加以下 5 行:

# A股短线跟踪 - 每个交易日
0 9 * * 1-5 cd /path/to/stock-tracker && python3 main.py pre_market >> /tmp/astock.log 2>&1
30 10 * * 1-5 cd /path/to/stock-tracker && python3 main.py intraday_1 >> /tmp/astock.log 2>&1
30 11 * * 1-5 cd /path/to/stock-tracker && python3 main.py midday >> /tmp/astock.log 2>&1
0 14 * * 1-5 cd /path/to/stock-tracker && python3 main.py intraday_3 >> /tmp/astock.log 2>&1
0 15 * * 1-5 cd /path/to/stock-tracker && python3 main.py close >> /tmp/astock.log 2>&1

Windows 计划任务:
  schtasks /create /tn "Astock-PreMarket" /tr "python3 C:\path\to\stock-tracker\main.py pre_market" /sc weekly /d mon,tue,wed,thu,fri /st 09:00
  (以此类推创建其他4个任务)

=====================================================================
或者使用 GitHub Actions 免费云端运行（推荐！无需自己的服务器）
=====================================================================
在项目目录创建 .github/workflows/astock-tracker.yml 即可
"""
import sys
import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

GITHUB_ACTIONS_YML = f"""name: A股短线跟踪

on:
  schedule:
    # 北京时间 09:00 = UTC 01:00
    - cron: '0 1 * * 1-5'
    # 北京时间 10:30 = UTC 02:30
    - cron: '30 2 * * 1-5'
    # 北京时间 11:30 = UTC 03:30
    - cron: '30 3 * * 1-5'
    # 北京时间 14:00 = UTC 06:00
    - cron: '0 6 * * 1-5'
    # 北京时间 15:00 = UTC 07:00
    - cron: '0 7 * * 1-5'
  workflow_dispatch:  # 允许手动触发

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install requests pyyaml pandas numpy
      
      - name: Determine report type
        id: report
        run: |
          HOUR=$(date -u +%H)
          MINUTE=$(date -u +%M)
          if [ "$HOUR" = "01" ] && [ "$MINUTE" -lt "30" ]; then
            echo "type=pre_market" >> $GITHUB_OUTPUT
          elif [ "$HOUR" = "02" ] && [ "$MINUTE" -ge "30" ]; then
            echo "type=intraday_1" >> $GITHUB_OUTPUT
          elif [ "$HOUR" = "03" ] && [ "$MINUTE" -ge "30" ]; then
            echo "type=midday" >> $GITHUB_OUTPUT
          elif [ "$HOUR" = "06" ] && [ "$MINUTE" -lt "30" ]; then
            echo "type=intraday_3" >> $GITHUB_OUTPUT
          elif [ "$HOUR" = "07" ] && [ "$MINUTE" -lt "30" ]; then
            echo "type=close" >> $GITHUB_OUTPUT
          else
            echo "type=skip" >> $GITHUB_OUTPUT
          fi
      
      - name: Run A-stock tracker
        if: steps.report.outputs.type != 'skip'
        env:
          BARK_DEVICE_KEY: ${{{{ secrets.BARK_DEVICE_KEY }}}}
        run: |
          mkdir -p /tmp/astock
          echo "$BARK_DEVICE_KEY" > .bark_key
          python3 main.py ${{{{ steps.report.outputs.type }}}}
"""


def print_deploy_guide():
    """打印部署指南"""
    print("=" * 60)
    print("📋 A股短线跟踪系统 — 独立部署指南")
    print("=" * 60)
    print()
    print("由于 CodeBuddy 沙箱在你退出后会休眠，")
    print("定时任务无法在后台持续运行。")
    print()
    print("以下三种方案任选其一：")
    print()
    
    print("【方案1】GitHub Actions（推荐 ⭐ 免费、无需服务器）")
    print("-" * 40)
    print("1. 把整个 stock-tracker 目录上传到 GitHub 仓库")
    print("2. 在仓库 Settings → Secrets → Actions 中添加:")
    print("   Name: BARK_DEVICE_KEY")
    print("   Value: jNVNkxWwVd88vNYoq7RxMa")
    print("3. 创建 .github/workflows/astock-tracker.yml")
    print("   (内容已生成在下方)")
    print()
    
    print("【方案2】自己的服务器/电脑 + crontab")
    print("-" * 40)
    print("1. 复制 stock-tracker 目录到服务器")
    print("2. pip install requests pyyaml pandas numpy")
    print("3. echo 'jNVNkxWwVd88vNYoq7RxMa' > .bark_key")
    print("4. 配置 crontab（见脚本顶部注释）")
    print()
    
    print("【方案3】保持 WorkBuddy 不关闭")
    print("-" * 40)
    print("只要 WorkBuddy 保持运行，当前定时任务就会正常触发。")
    print("适合白天盯盘时使用。")
    print()
    
    print("=" * 60)
    print("📄 GitHub Actions 工作流配置：")
    print("=" * 60)
    print()
    print(GITHUB_ACTIONS_YML)


if __name__ == '__main__':
    print_deploy_guide()
    
    # 也保存到文件
    workflow_dir = os.path.join(PROJECT_DIR, '.github', 'workflows')
    os.makedirs(workflow_dir, exist_ok=True)
    workflow_file = os.path.join(workflow_dir, 'astock-tracker.yml')
    with open(workflow_file, 'w', encoding='utf-8') as f:
        f.write(GITHUB_ACTIONS_YML)
    print(f"\n✅ GitHub Actions 配置已保存: {workflow_file}")
