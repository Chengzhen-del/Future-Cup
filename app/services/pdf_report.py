"""v8：巡检报告 PDF 导出（reportlab，中文字体自动探测）。

只做「一张 A4 报告」：基本信息 + 判读结论 + 判读明细 + 现场照片 + 执行步骤。
返回生成的临时文件路径，由路由层以 FileResponse 下发。
"""
import tempfile
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                               TableStyle)

from app.config import settings

_FONT = ""

_LEVEL_COLOR = {"正常": colors.HexColor("#1a7f37"), "关注": colors.HexColor("#b26a00"),
                "异常": colors.HexColor("#c62828"), "紧急": colors.HexColor("#8e0000")}


def _register_font() -> str:
    """中文字体：优先系统 TTF，找不到退化为 reportlab 内置 STSong-Light。"""
    global _FONT
    if _FONT:
        return _FONT
    candidates = [
        (r"C:\Windows\Fonts\msyh.ttc", 0),
        (r"C:\Windows\Fonts\simhei.ttf", None),
        (r"C:\Windows\Fonts\simsun.ttc", 0),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ]
    for path, idx in candidates:
        if not Path(path).is_file():
            continue
        name = "CJK-" + Path(path).stem + str(idx)
        try:
            font = TTFont(name, path) if idx is None else TTFont(name, path, subfontIndex=idx)
            pdfmetrics.registerFont(font)
            _FONT = name
            return name
        except Exception:  # noqa: BLE001
            continue
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _FONT = "STSong-Light"
    except Exception:  # noqa: BLE001
        _FONT = "Helvetica"
    return _FONT


def _esc(v) -> str:
    return (str(v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _p(text, style) -> Paragraph:
    return Paragraph(_esc(text), style)


def render_inspection_pdf(d: dict) -> str:
    """d 为 store.get_inspection 的返回（含 findings / steps）。"""
    font = _register_font()
    base = ParagraphStyle("base", fontName=font, fontSize=9, leading=14, wordWrap="CJK")
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=12,
                           textColor=colors.HexColor("#555555"))
    title = ParagraphStyle("title", parent=base, fontSize=18, leading=24,
                           spaceAfter=2, alignment=1)
    h2 = ParagraphStyle("h2", parent=base, fontSize=11, leading=16,
                        spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#0b5394"))

    out_dir = Path(tempfile.mkdtemp(prefix="ia_pdf_"))
    out = out_dir / f"{d.get('id') or 'inspection'}.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4, title=f"巡检报告 {d.get('id', '')}",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=14 * mm)
    flow = [
        _p("智巡 InspectAgent · 巡检报告", title),
        Paragraph(_esc(f"报告编号 {d.get('id', '')}　生成时间 "
                       f"{datetime.now():%Y-%m-%d %H:%M}　"
                       f"{'【MOCK 演示数据】' if d.get('mock') else ''}"), small),
        Spacer(1, 6),
        _p("一、巡检基本信息", h2),
    ]

    info = [
        ("设备名称", d.get("deviceName") or "-", "设备编号", d.get("deviceId") or "-"),
        ("安装位置", d.get("location") or "-", "关联任务", d.get("taskId") or "-"),
        ("巡检人员", d.get("operator") or "-", "巡检时间",
         d.get("capturedAt") or d.get("createdAt") or "-"),
        ("语音描述", d.get("voiceText") or "-", "工单编号", d.get("workOrderId") or "-"),
    ]
    tbl = Table([[Paragraph(f"<b>{_esc(a)}</b>", base), _p(b, base),
                  Paragraph(f"<b>{_esc(c)}</b>", base), _p(dd, base)] for a, b, c, dd in info],
                colWidths=[24 * mm, 62 * mm, 24 * mm, 62 * mm], splitInRow=1)
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f7fa")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f5f7fa")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow += [tbl, _p("二、判读结论", h2)]

    level = d.get("level") or "正常"
    color = _LEVEL_COLOR.get(level, colors.black)
    advice_style = ParagraphStyle("advice", parent=base, fontSize=9.5, leading=15)
    flow.append(Table(
        [[Paragraph(f"<b>等级</b>", base),
          Paragraph(f'<font color="{color.hexval()}"><b>{_esc(level)}</b></font>', base),
          Paragraph("<b>置信度</b>", base),
          _p(f"{float(d.get('confidence') or 0) * 100:.1f}%", base),
          Paragraph("<b>需人工复核</b>", base),
          _p("是" if d.get("needHuman") else "否", base)]],
        colWidths=[18 * mm, 30 * mm, 20 * mm, 30 * mm, 26 * mm, 48 * mm],
        style=TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                          ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f7fa")),
                          ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f5f7fa")),
                          ("BACKGROUND", (4, 0), (4, -1), colors.HexColor("#f5f7fa")),
                          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                          ("TOPPADDING", (0, 0), (-1, -1), 5),
                          ("BOTTOMPADDING", (0, 0), (-1, -1), 5)])))
    flow += [Spacer(1, 5), _p("处置建议", small), _p(d.get("advice") or "-", advice_style)]

    findings = d.get("findings") or []
    if findings:
        flow.append(_p("三、逐项判读", h2))
        rows = [[Paragraph("<b>检查项</b>", base), Paragraph("<b>实测/判读</b>", base),
                 Paragraph("<b>判定</b>", base), Paragraph("<b>依据</b>", base)]]
        for f in findings:
            bad = bool(f.get("abnormal"))
            rows.append([
                _p(f.get("item"), base),
                _p(f.get("value"), base),
                Paragraph(f'<font color="{"#c62828" if bad else "#1a7f37"}">'
                          f'{"异常" if bad else "正常"}</font>', base),
                _p(f.get("basis"), base),
            ])
        ft = Table(rows, colWidths=[34 * mm, 52 * mm, 16 * mm, 70 * mm], repeatRows=1,
                   splitInRow=1)
        ft.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f9")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(ft)

    image_name = d.get("imageId") or ""
    image_path = settings.UPLOAD_DIR / image_name
    if image_name and image_path.is_file():
        flow.append(_p("四、现场照片", h2))
        try:
            img = Image(str(image_path))
            ratio = min(1.0, (150 * mm) / img.imageWidth)
            img.drawWidth = img.imageWidth * ratio
            img.drawHeight = img.imageHeight * ratio
            flow.append(img)
        except Exception:  # noqa: BLE001
            flow.append(_p("（照片无法嵌入，请到报告页查看原图）", small))

    steps = d.get("steps") or []
    if steps:
        flow.append(_p("五、执行过程", h2))
        for i, s in enumerate(steps, 1):
            if not isinstance(s, dict):
                continue
            name = s.get("name") or s.get("stepName") or s.get("step") or ""
            status = s.get("status") or ""
            ms = s.get("durationMs") or s.get("ms") or ""
            flow.append(_p(f"{i}. {name} {status} {f'{ms}ms' if ms else ''}".strip(), small))

    flow += [Spacer(1, 10),
             _p(f"本报告由智巡 InspectAgent 自动生成 · {datetime.now():%Y-%m-%d %H:%M:%S}", small)]
    doc.build(flow)
    return str(out)
