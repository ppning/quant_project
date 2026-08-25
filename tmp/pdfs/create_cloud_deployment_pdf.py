from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path("/Users/ningpeipei/Documents/quant_project")
OUTPUT = ROOT / "output" / "pdf" / "量化研究工作台云端部署留档.pdf"
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"


def register_fonts() -> str:
    font_name = "STHeiti"
    pdfmetrics.registerFont(TTFont(font_name, FONT_PATH))
    return font_name


FONT = register_fonts()


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=FONT,
            fontSize=22,
            leading=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0f4c75"),
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#667085"),
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=FONT,
            fontSize=15,
            leading=22,
            textColor=colors.HexColor("#146c94"),
            spaceBefore=10,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=FONT,
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#1f2933"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9.5,
            leading=15,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1f2933"),
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#667085"),
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#1f2933"),
        ),
        "cell_head": ParagraphStyle(
            "cell_head",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=colors.white,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Code"],
            fontName=FONT,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#1f2933"),
            backColor=colors.HexColor("#f2f4f7"),
            borderColor=colors.HexColor("#d9dee7"),
            borderWidth=0.4,
            borderPadding=5,
            spaceBefore=4,
            spaceAfter=7,
        ),
    }


S = make_styles()


def p(text: str, style: str = "body"):
    return Paragraph(text, S[style])


def bullets(items: list[str]):
    story = []
    for item in items:
        story.append(p(f"- {item}"))
    return story


def table(data, widths):
    prepared = []
    for row_idx, row in enumerate(data):
        prepared.append([
            Paragraph(str(cell), S["cell_head" if row_idx == 0 else "cell"])
            for cell in row
        ])
    t = Table(prepared, colWidths=widths, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#146c94")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9dee7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    return t


def draw_page(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(18 * mm, 12 * mm, "量化研究工作台云端部署留档")
    canvas.drawRightString(192 * mm, 12 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_pdf():
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin + 6 * mm, doc.width, doc.height - 6 * mm, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_page)])

    story = [
        p("量化研究工作台云端部署留档", "title"),
        p("整理范围：从云端部署条件开始，包含阿里云 ECS 购买建议、价格口径、配置选择、安全注意事项和推荐部署架构。", "subtitle"),
        p("1. 云端部署需要什么", "h1"),
        p("当前本地系统由 Python Web 服务、量化策略工作台、单股诊断 skill、TradingAgent 多 Agent 项目、本地缓存和报告文件组成。部署到云端时，需要把这些运行条件迁移到服务器，并用进程守护方式长期运行。"),
        p("1.1 基础条件", "h2"),
        *bullets([
            "云服务器：建议使用 Linux 服务器，Ubuntu 22.04 或 Ubuntu 24.04。",
            "公网访问：需要公网 IPv4 或域名。没有域名也可以用 http://服务器公网IP 访问。",
            "Python 环境：建议 Python 3.10+；当前本地使用 Python 3.12。",
            "项目文件：需要上传 quant_project、tradingagent-main、my-skills、必要的数据缓存和 reports。",
            "API Key：需要在服务器配置 ZAI_API_KEY、MX_APIKEY 或 EASTMONEY_APIKEY，以及其他实际使用的 LLM/API key。",
            "外网访问：服务器需要能访问东方财富/AkShare 数据源、TradingAgent 使用的 LLM provider，以及各类 skill 接口。",
            "进程守护：不能只靠手动 python3 server.py。正式部署建议使用 systemd、supervisor、pm2 或 Docker。",
            "安全措施：公网访问前建议配置登录保护、Nginx Basic Auth、HTTPS 和安全组规则。",
        ]),
        p("1.2 推荐部署架构", "h2"),
        p("推荐使用 Nginx 作为公网入口，Python 服务只监听服务器本机 127.0.0.1:8765。这样可以避免直接暴露 Python 简易服务。"),
        p("浏览器 -> 公网 IP/域名:80/443 -> Nginx -> 127.0.0.1:8765", "code"),
        p("1.3 当前代码需要注意的点", "h2"),
        *bullets([
            "如果使用 Nginx 反向代理，server.py 继续监听 127.0.0.1:8765 即可。",
            "如果临时直接公网访问，需要把监听地址改成 0.0.0.0:8765，并在安全组开放 8765；但不建议长期这样暴露。",
            "TradingAgent 路径目前写入了本机路径 /Users/ningpeipei/Downloads/tradingagent-main；部署时应改成服务器路径，例如 /opt/tradingagent-main。",
            "桌面快捷方式只适用于本机；云端访问建议用域名或公网 IP。",
        ]),
        p("2. 阿里云服务器购买要点", "h1"),
        p("阿里云可以购买 ECS 云服务器。购买服务器后默认会有内网 IP；公网 IP 需要在购买时勾选分配公网 IPv4 或配置公网带宽。"),
        p("2.1 购买时重点选项", "h2"),
        *bullets([
            "产品：ECS 云服务器。",
            "地域：选离使用者较近的地域，例如华东或华南。",
            "操作系统：Ubuntu 22.04 或 Ubuntu 24.04。",
            "公网 IP：勾选分配公网 IPv4。",
            "带宽：测试期建议 1-5 Mbps；本项目建议先选 3 Mbps。",
            "安全组：开放 22(SSH)、80(HTTP)、443(HTTPS)。如果不用 Nginx，可临时开放 8765。",
        ]),
        p("2.2 IP 地址说明", "h2"),
        *bullets([
            "内网 IP：云服务器默认会有，只能在阿里云内网访问。",
            "公网 IP：需要购买时选择公网带宽或分配公网 IPv4，之后才能从浏览器公网访问。",
            "正式访问建议：公网 IP 或域名 -> Nginx -> 本机 127.0.0.1:8765。",
        ]),
        PageBreak(),
        p("3. 配置建议与价格口径", "h1"),
        p("价格会随地域、实例规格、带宽、系统盘、购买时长、是否新用户活动而变化。以下为选型建议，实际下单价格以阿里云购买页/价格计算器为准。"),
        table([
            ["用途", "推荐配置", "适合情况", "价格口径"],
            ["最低可跑", "2核4G + 40G系统盘 + 1-3M带宽", "Home 页、策略工作台、单股诊断、小量访问", "活动页显示 2核4G 9.9/月起；部分活动低至 68元/年"],
            ["推荐配置", "4核8G + 80G系统盘 + 3-5M带宽", "更适合 TradingAgent 多 Agent 分析和报告生成", "需进入购买页或价格计算器确认"],
            ["更稳配置", "4核16G 或 8核16G + 100G盘", "多人访问、频繁运行 TradingAgent、更多缓存和报告", "成本更高，初期不建议直接购买"],
        ], [30 * mm, 48 * mm, 58 * mm, 38 * mm]),
        Spacer(1, 8),
        p("3.1 推荐购买方案", "h2"),
        p("如果只是自己使用、访问量不大，可以先购买 2核4G 活动机部署验证。如果经常运行 TradingAgent，建议使用 4核8G，内存和 CPU 都更稳。"),
        p("建议初始规格：ECS 云服务器 + Ubuntu 22.04/24.04 + 2核4G 或 4核8G + 80G系统盘 + 公网 IPv4 + 3M 带宽。", "code"),
        p("3.2 成本组成", "h2"),
        *bullets([
            "ECS 实例费用：CPU/内存规格决定基础价格。",
            "系统盘费用：建议 40-80G 起步；TradingAgent 报告和缓存较多时建议 80G。",
            "公网带宽费用：1-5 Mbps 适合个人测试；多人访问可提高。",
            "快照备份费用：可选，但建议重要项目开启快照。",
            "域名费用：可选；没有域名可先用公网 IP。",
            "HTTPS 证书：可使用免费证书。",
            "LLM/API 调用费用：不包含在服务器费用里，需要单独按 provider 计费。",
        ]),
        p("4. 部署步骤草案", "h1"),
        p("以下是云端部署的大致步骤，实际执行时需要根据服务器系统、目录和 Python 环境微调。"),
        p("""# 1. 上传项目
scp -r quant_project user@server:/opt/quant_project
scp -r tradingagent-main user@server:/opt/tradingagent-main

# 2. 安装 Python 环境和依赖
cd /opt/quant_project
python3 -m venv .venv
source .venv/bin/activate
pip install -r /opt/tradingagent-main/requirements.txt

# 3. 配置环境变量
nano /opt/quant_project/.env

# 4. 启动本地服务
python3 server.py

# 5. 配置 systemd 和 Nginx
# systemd 负责后台常驻，Nginx 负责公网访问和 HTTPS。""", "code"),
        p("5. 安全建议", "h1"),
        *bullets([
            "不要长期直接把 8765 暴露到公网。",
            "推荐用 Nginx 反代，并限制 Python 服务只监听 127.0.0.1。",
            "开启 HTTPS，避免 API Key、查询内容或报告路径在公网明文传输。",
            "至少增加 Basic Auth 或登录保护，避免任何人访问你的分析工作台。",
            "安全组只开放 22、80、443，SSH 建议限制来源 IP。",
            "API Key 写入服务器环境变量或 .env，不要写死到代码和日志中。",
        ]),
        p("6. 信息来源与备注", "h1"),
        *bullets([
            "阿里云 ECS 活动页：https://www.aliyun.com/daily-act/ecs/activity_selection",
            "阿里云 ECS 产品页：https://www.aliyun.com/product/ecs",
            "价格信息具有时效性，本文中的 9.9/月起、68元/年属于活动页口径，最终以阿里云购买页实时价格为准。",
            "本项目涉及金融分析和自动化报告，输出仅供研究参考，不构成投资建议。",
        ]),
    ]
    doc.build(story)


if __name__ == "__main__":
    build_pdf()
    print(OUTPUT)
