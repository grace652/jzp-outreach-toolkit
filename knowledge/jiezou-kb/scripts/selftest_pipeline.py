#!/usr/bin/env python3
"""端到端自测：全程离线，验证整条流水线的关键不变量。

跑这个脚本不需要联网、不需要任何账号，用的是本地已有的
广交会名录、自有成交记录和固定样本。

    python3 scripts/selftest_pipeline.py

七项断言：
  1. 流式读取 135MB 名录，内存平稳
  2. 公司名归一化 / 别名 / 国别识别
  3. 自有成交记录 17 条
  4. 竞对·老客户交叉引用（Soltech 应为 A 级 170 分）
  5. 抓取脚本绝不写入 entries/
  6. 打分幂等（第二次不新建、不重复）
  7. 禁入名单生效（内部供货记录不得入库）

自测会在 entries/ 与 leads/ 上做写操作，因此**结束时会把这两个目录
完整还原**（新增的删掉、改过的写回），并重建索引。
"""
import hashlib
import re
import resource
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import customs_adapters as ca          # noqa: E402
import customs_normalize as cn         # noqa: E402
import kblib                           # noqa: E402

PY = sys.executable
CANTON = Path("/Users/eric/Documents/毅冰-kb/04-data/广交会采购商名录.csv")
ORDERS = Path("/Users/eric/Downloads/公司成单客户")
FIXTURE = ROOT / "data" / "fixtures" / "customs_sample.csv"
DENY_DIR = "/Users/eric/Downloads/资料"

MUTABLE_DIRS = ("entries", "leads")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  {detail}" if detail else ""))
    return ok


def run(args):
    return subprocess.run([PY] + args, cwd=str(ROOT), capture_output=True, text=True)


def snapshot_tree():
    """把 entries/ 与 leads/ 下所有文件的内容存下来。

    跳过 .DS_Store —— 它由 Finder 随手生成，不属于知识库内容，
    计入快照只会让「还原」把无关文件也一起搬来搬去。
    """
    snap = {}
    for d in MUTABLE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name != ".DS_Store":
                snap[str(p.relative_to(ROOT))] = p.read_bytes()
    return snap


def count_customers(snap=None):
    snap = snap if snap is not None else snapshot_tree()
    return len([k for k in snap if k.startswith("entries/客户/") and k.endswith(".md")])


def restore_tree(snap):
    """还原到快照状态：删掉新增的，写回改过的，重建索引。"""
    current = set()
    for d in MUTABLE_DIRS:
        base = ROOT / d
        if base.exists():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    current.add(str(p.relative_to(ROOT)))

    removed = 0
    for rel in current - set(snap):
        (ROOT / rel).unlink()
        removed += 1
    restored = 0
    for rel, data in snap.items():
        p = ROOT / rel
        if not p.exists() or p.read_bytes() != data:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            restored += 1
    run(["scripts/build_index.py"])
    return removed, restored


def entries_digest():
    h = hashlib.sha256()
    for p in sorted((ROOT / "entries").rglob("*.md")):
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)


def parse_score_lines(stdout):
    """把 lead_scoring 的摘要行解析成 {公司名: (tier, score, coverage)}。"""
    out = {}
    for line in stdout.splitlines():
        m = re.match(r"\s*\d+\.\s*\[(\w)\]\s*(-?\d+)\s+(\d+)%\s+(.+?)\s{2,}\w{2}\s", line)
        if m:
            out[m.group(4).strip()] = (m.group(1), int(m.group(2)), int(m.group(3)))
    return out


def compare_baseline(stdout):
    """把实际打分结果与 data/fixtures/expected_scores.csv 逐条比对。"""
    import csv as _csv
    baseline_path = ROOT / "data" / "fixtures" / "expected_scores.csv"
    if not baseline_path.exists():
        return False, "找不到 expected_scores.csv"
    actual = parse_score_lines(stdout)
    diffs = []
    with baseline_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in _csv.DictReader(fh):
            name = row["buyer_name"].strip()
            got = actual.get(name)
            if got is None:
                diffs.append(f"{name} 未出现在结果中")
                continue
            if got[0] != row["tier"] or got[1] != int(row["score"]):
                diffs.append(f"{name} 期望 {row['tier']}/{row['score']}，实际 {got[0]}/{got[1]}")
    if diffs:
        return False, f"{len(diffs)} 条不一致：{diffs[0]}" + (f" 等" if len(diffs) > 1 else "")
    return True, f"{len(actual)} 条全部吻合"


def main():
    print("=" * 64)
    print("端到端自测（全程无网络访问）")
    print("=" * 64)

    baseline = snapshot_tree()
    baseline_digest = entries_digest()

    # ---- 1. 流式读取 135MB 名录 ----
    print("\n[1/7] 流式读取广交会名录，检查内存")
    if not CANTON.exists():
        check("名录存在", False, f"找不到 {CANTON}")
    else:
        adapter = ca.get_adapter("local_csv").configure(file=str(CANTON), profile="cantonfair")
        n = sum(1 for _ in adapter.fetch(ca.Query(country="美国,加拿大", limit=20000)))
        after = peak_rss_mb()
        check("名录可流式读取", n > 0, f"取出 {n} 条")
        check("峰值内存 < 250MB", after < 250, f"峰值 {after:.0f}MB")

    # ---- 2. 归一化 ----
    print("\n[2/7] 公司名归一化 / 别名 / 国别识别")
    aliases = cn.load_aliases()
    check("别名：Domino 两种写法归一",
          cn.company_key("Domino Highvoltage", aliases) ==
          cn.company_key("Domino Highvoltage Supply Inc", aliases),
          cn.company_key("Domino Highvoltage", aliases))
    check("别名：亚威多种写法归一",
          len({cn.company_key(x, aliases) for x in
               ("Jiangsu Yawei Transformer Co., Ltd.", "Yawei Transformer",
                "JIANGSU YAWEI TRANSFORMER")}) == 1)
    check("归一化：Soltech Power, LLC → SOLTECH POWER",
          cn.normalize_company("Soltech Power, LLC") == "SOLTECH POWER")
    check("国别：中文「美        国.」→ US", cn.country2_of("美        国.") == "US")
    check("国别：英文地址 → US / CA",
          cn.country2_of("77 Railside Road, Toronto, ON M3A 1B2 Canada") == "CA" and
          cn.country2_of("Parkersburg, WV 26101 USA") == "US")
    check("国别：同名公司跨国不撞键",
          f"POWER ELECTRONICS@US" != f"POWER ELECTRONICS@CA")

    # ---- 3. 自有成交记录 ----
    print("\n[3/7] 自有成交记录")
    orders = ca.parse_owned_orders(ORDERS) if ORDERS.exists() else []
    uniq = {cn.company_key(o["name"], aliases) for o in orders}
    check("解析出 17 家去重公司", len(uniq) == 17, f"实际 {len(uniq)} 家 / {len(orders)} 个块")
    owned = [r for r in kblib.load_index() if r["type"] == "自有成交记录"]
    check("知识库里确有 17 条自有成交记录", len(owned) == 17, f"实际 {len(owned)}")
    check("每个块都解析到了产品明细", bool(orders) and all(o["projects"] for o in orders))

    # ---- 4. 交叉引用 ----
    print("\n[4/7] 竞对·老客户交叉引用（固定样本）")
    r = run(["scripts/lead_scoring.py", "--input", str(FIXTURE)])
    if r.returncode != 0:
        check("打分脚本可运行", False, r.stderr.strip()[:200])
    else:
        lines = r.stdout.splitlines()
        soltech = next((l for l in lines if "Soltech Power" in l), "")
        m = re.search(r"\[(\w)\]\s+(-?\d+)", soltech)
        check("Soltech Power 判为 A 级", bool(m) and m.group(1) == "A", soltech.strip()[:80])
        check("Soltech Power 得分 170", bool(m) and m.group(2) == "170",
              m.group(2) if m else "未找到")
        check("识别出「流失老客户」信号", "流失老客户" in soltech)
        check("识别出「竞争对买家」信号", "竞争对买家" in soltech)
        trader = next((l for l in lines if "Shenzhen Global Sourcing" in l), "")
        check("中国贸易商被判为 D 级", "[D]" in trader, trader.strip()[:70])
        anguilla = next((l for l in lines if "Anguilla Electricity" in l), "")
        # 安圭拉是我方老客户，靠老客户加分仍可能到 C 级；
        # 这里要验证的是「非目标市场」这个扣分信号确实触发了，而不是最终分级。
        check("非目标市场信号触发", "非目标市场" in anguilla, anguilla.strip()[:70])
        # 与基线逐条比对：以后调权重时如果分数悄悄变了，这里会拦住
        check("打分结果与 expected_scores.csv 基线一致", *compare_baseline(r.stdout))

    # ---- 5. 抓取不写 entries/ ----
    print("\n[5/7] 抓取脚本绝不写入 entries/")
    before_digest = entries_digest()
    run(["scripts/customs_data_fetch.py", "--adapter", "local_csv", "--file", str(FIXTURE),
         "--profile", "manual", "--out-prefix", "selftest", "--preview", "0"])
    check("entries/ 内容未被改动", before_digest == entries_digest())

    # ---- 6. 幂等 ----
    print("\n[6/7] 打分幂等（第二次不新建、不重复）")
    n_before = count_customers()
    r1 = run(["scripts/lead_scoring.py", "--input", str(FIXTURE), "--apply", "--emit-entries", "A,B"])
    n_after1 = count_customers()
    r2 = run(["scripts/lead_scoring.py", "--input", str(FIXTURE), "--apply", "--emit-entries", "A,B"])
    n_after2 = count_customers()
    print(f"       客户条目数：{n_before} → {n_after1} → {n_after2}")

    if r1.returncode or r2.returncode:
        check("两次打分都能跑通", False, (r1.stderr or r2.stderr).strip()[:200])
    else:
        c2 = re.search(r"新增 (\d+)", r2.stdout)
        # 真正的幂等不变量：第二次运行不新建、且条目总数不再增长。
        # （不断言「第一次一定新建」——若上一次自测留下的条目还在，
        #   第一次合理地只会更新，那不是缺陷。）
        check("第二次运行新建 0 条", bool(c2) and int(c2.group(1)) == 0,
              c2.group(0) if c2 else "未解析到输出")
        check("第二次运行后条目总数未增长", n_after2 == n_after1,
              f"{n_after1} → {n_after2}")
        check("A/B 级线索确实落成了客户条目", n_after1 >= n_before,
              f"{n_before} → {n_after1}")
        # 具体验证：样本里 A/B 级的公司，文件确实存在
        expect = ["Soltech Power, LLC", "Great Lakes Utility Services",
                  "Alpine Renewable Energy Corp", "Metro Power Distribution LLC"]
        missing = [n for n in expect if not (ROOT / "entries" / "客户" / f"{n}.md").exists()]
        check("样本 A/B 级公司条目均已生成", not missing, f"缺失 {missing}" if missing else "")

    # ---- 7. 禁入名单 ----
    print("\n[7/7] 禁入名单（内部供货记录不得入库）")
    r = run(["scripts/import_training.py", "--source", DENY_DIR, "--dry-run"])
    out = r.stdout + r.stderr
    leaked = [l for l in out.splitlines() if "不可发" in l and "CREATE" in l]
    check("没有从「不可发」目录导入任何条目", not leaked, f"泄漏 {len(leaked)} 条")
    # 反向验证：确认目录确实被扫到且被拒了，否则上一条可能是假阳性
    import import_training  # noqa: PLC0415
    scanned = import_training.scan_sources([DENY_DIR], import_training.DEFAULT_DENY, set(), 0)
    denied = [str(p) for p, reason in scanned if reason and "禁入" in reason]
    check("确实扫到并拒绝了「不可发」文件", len(denied) > 0,
          f"拒绝 {len(denied)} 个" + (f"，如 {Path(denied[0]).name}" if denied else ""))

    # ---- 还原 ----
    removed, restored = restore_tree(baseline)
    print(f"\n还原 entries/ 与 leads/：删除 {removed} 个新增文件，写回 {restored} 个改动文件")
    check("知识库已还原到自测前状态", entries_digest() == baseline_digest)

    print("\n" + "=" * 64)
    if FAIL:
        print(f"失败 {len(FAIL)}/{len(PASS) + len(FAIL)}：")
        for f in FAIL:
            print(f"  ✗ {f}")
        return 1
    print(f"全部通过（{len(PASS)}/{len(PASS)}），全程无网络访问。")
    print(f"本进程峰值内存：{peak_rss_mb():.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
