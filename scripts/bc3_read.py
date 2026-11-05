#!/usr/bin/env python3
"""BC3 (FIEBDC-3) budget -> BOQ lines + the element behind each measurement, when the budget names one.

Usage: py scripts/bc3_read.py budget.bc3 outputs/<p>/

Writes bc3_lines.csv (one row per line per chapter) and bc3_measures.csv (line, IFC GlobalId, quantity).
"""
import csv
import os
import re
import sys

B = chr(92)
GUID = re.compile(r"#([0-9A-Za-z_$]{22})\b")


def fnum(s):
    try:
        return float(s)
    except ValueError:
        return None


def row_qty(row, formula):
    vals = [fnum(x) for x in row[2:6]]
    if formula:
        env = dict(zip("ABCD", [v or 0 for v in vals]))
        expr = re.sub(r"[A-D]", lambda m: str(env[m.group()]), formula.replace("^", "**"))
        if re.fullmatch(r"[0-9.+\-*/() e]+", expr):
            return float(eval(expr))
    q = 1.0
    for v in vals:
        if v is not None:
            q *= v
    return q if any(v is not None for v in vals) else None


def main():
    src, out = sys.argv[1:3]
    recs = [r for r in open(src, "rb").read().decode("cp1252").split("~") if r.strip()]
    con, kids, meas = {}, {}, {}
    for r in recs:
        p = r.split("|")
        if r[0] == "C":
            con[p[1].split(B)[0]] = {"unit": p[2], "desc": p[3].strip(), "rate": float(p[4].split(B)[0] or 0)}
        elif r[0] == "D":
            x = p[2].split(B)
            kids[p[1]] = [(x[i], float(x[i + 2] or 0)) for i in range(0, len(x) - 2, 3)]
        elif r[0] == "M":
            meas[tuple(p[1].split(B)[:2])] = p
    root = next(k for k in con if k.endswith("##"))

    def price(c):
        """Rates leave out their % items (auxiliary means, a share of the labour), so build them up from the breakdown."""
        if c not in kids or c.endswith("#"):
            return con[c]["rate"]
        total = labour = pct = 0.0
        for k, q in kids[c]:
            if k.startswith("%"):
                pct += q
                continue
            v = q * price(k)
            total += v
            labour += v if k.startswith("A") else 0
        return total + pct * labour

    lines, rows = [], []

    def walk(c, path):
        for k, q in kids.get(c, []):
            if k.endswith("#"):
                walk(k, path + [con[k]["desc"]])
                continue
            v = con[k]
            lines.append({"chapter_code": c, "chapter": " / ".join(path), "code": k, "unit": v["unit"], "desc": v["desc"], "qty": q,
                          "rate": round(price(k), 5), "amount": round(q * price(k), 2)})
            m = meas.get((c, k))
            if not m:
                continue
            f = m[4].split(B) if len(m) > 4 else []
            formula = None
            for i in range(0, len(f) - 5, 6):
                row = f[i:i + 6]
                if row[0] == "3":
                    formula = row[1]
                    continue
                g = GUID.search(row[1])
                qty = row_qty(row, formula)
                if g and qty is not None:
                    rows.append({"chapter_code": c, "code": k, "guid": g.group(1), "qty": qty, "note": row[1][:90]})

    walk(root, [])
    os.makedirs(out, exist_ok=True)
    for name, data in (("bc3_lines.csv", lines), ("bc3_measures.csv", rows)):
        with open(os.path.join(out, name), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, list(data[0]))
            w.writeheader()
            w.writerows(data)
    total = sum(x["amount"] for x in lines)
    print({"lines": len(lines), "total": round(total, 2), "stated": con[root]["rate"], "measures_with_guid": len(rows),
           "lines_with_guid": len({(r["chapter_code"], r["code"]) for r in rows}), "elements": len({r["guid"] for r in rows})})


if __name__ == "__main__":
    main()
