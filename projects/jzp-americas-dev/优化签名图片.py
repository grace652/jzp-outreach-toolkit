#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
签名图片优化器
==============
把签名里的 7 张图按「实际显示尺寸的 2 倍」重采样（Retina 够用又不浪费），
并压缩到合理体积。

背景：
  - 原图严重超采样（Logo 2026px 只显示 93px，超 21 倍）
  - 合计 333 KB，会触发 Gmail 的 102 KB 折叠
  - 且远程引用被 Gmail / macOS Mail 默认屏蔽

产出：`签名图片_压缩/` 下的优化图 + 体积对比报告
"""

from pathlib import Path
from PIL import Image
import io

SRC = Path(__file__).resolve().parent / "_签名图片"
DST = Path(__file__).resolve().parent / "签名图片_压缩"

# 文件名 → (目标宽度, 输出格式, 说明)
# 目标宽度 = 显示宽度 × 2（Retina）
SPEC = {
    "01.png": (186, "PNG", "Logo（93px 显示）"),
    "02.jpg": (426, "JPEG", "认证标识条（213px 显示）"),
    "03.jpg": (528, "JPEG", "产品图（264px 显示）"),
    "04.png": (30, "PNG", "Facebook 图标（15px 显示）"),
    "05.png": (30, "PNG", "Twitter 图标（15px 显示）"),
    "06.png": (30, "PNG", "LinkedIn 图标（15px 显示）"),
    "07.png": (30, "PNG", "Instagram 图标（15px 显示）"),
}

if not DST.exists():
    DST.mkdir(parents=True)


def optimize(src: Path, target_w: int, fmt: str) -> bytes:
    im = Image.open(src)
    w, h = im.size
    if w > target_w:
        im = im.resize((target_w, round(h * target_w / w)), Image.LANCZOS)

    buf = io.BytesIO()
    if fmt == "JPEG":
        im.convert("RGB").save(buf, "JPEG", quality=80, optimize=True,
                               progressive=True)
    else:
        # 图标类多为纯色，量化调色板能大幅瘦身
        if im.mode == "RGBA":
            im.save(buf, "PNG", optimize=True)
        else:
            im.convert("P", palette=Image.ADAPTIVE, colors=128).save(
                buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    rows, before, after = [], 0, 0
    for name, (tw, fmt, note) in SPEC.items():
        src = SRC / name
        if not src.exists():
            print(f"⚠️  缺少 {name}")
            continue
        orig = src.stat().st_size
        data = optimize(src, tw, fmt)
        out = DST / name
        out.write_bytes(data)

        im0 = Image.open(src).size
        im1 = Image.open(out).size
        rows.append((name, f"{im0[0]}x{im0[1]}", f"{im1[0]}x{im1[1]}",
                     orig, len(data), note))
        before += orig
        after += len(data)

    print(f"{'文件':10} {'原尺寸':>12} {'压缩后':>10} {'原体积':>10} {'压缩后':>10}  说明")
    print("─" * 88)
    for n, a, b, o, s, note in rows:
        print(f"{n:10} {a:>12} {b:>10} {o/1024:>8.1f}K {s/1024:>8.1f}K  {note}")
    print("─" * 88)
    print(f"{'合计':10} {'':>12} {'':>10} {before/1024:>8.1f}K {after/1024:>8.1f}K"
          f"  省 {(1-after/before)*100:.0f}%")
    print()
    print(f"输出目录：{DST}")
    print(f"内嵌后 base64 膨胀约 33% → 约 {after*1.33/1024:.0f} KB")
    print(f"Gmail 折叠阈值：102 KB → {'✅ 安全' if after*1.33 < 102*1024 else '⚠️ 仍超'}")

    # 重新生成签名 HTML（cid: 引用）
    sig = (Path(__file__).resolve().parent / "签名.html").read_text(encoding="utf-8")
    mapping = {
        "https://cdnus.globalso.com/jiezoupower/jzp7.png": "logo",
        "https://sc04.alicdn.com/kf/H2ddee5292cfa4cf487ca73079a5b727d0/276161364/H2ddee5292cfa4cf487ca73079a5b727d0.jpg": "certs",
        "https://sc04.alicdn.com/kf/Hd6c02f3e2bfc4b5f9b67e32646fcee5al/276161364/Hd6c02f3e2bfc4b5f9b67e32646fcee5al.jpg": "products",
        "https://cdnus.globalso.com/jiezoupower/facebook1.png": "facebook",
        "https://cdnus.globalso.com/jiezoupower/twitter5.png": "twitter",
        "https://cdnus.globalso.com/jiezoupower/linkedin1.png": "linkedin",
        "https://cdnus.globalso.com/jiezoupower/Instagram.png": "instagram",
    }
    for url, cid in mapping.items():
        sig = sig.replace(f'src="{url}"', f'src="cid:{cid}"')
    out_html = Path(__file__).resolve().parent / "签名_内嵌版.html"
    out_html.write_text(sig, encoding="utf-8")
    print(f"已生成内嵌版签名：{out_html}")
    print(f"  cid 引用数：{sig.count('cid:')} / 7")


if __name__ == "__main__":
    main()
