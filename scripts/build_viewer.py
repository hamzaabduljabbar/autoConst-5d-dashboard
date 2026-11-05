#!/usr/bin/env python3
"""model.json + model.bin -> one offline HTML with the date slider.

Usage: py scripts/build_viewer.py outputs/<p>/priced.json outputs/<p>/5d.html --project "Name" --credit "..."
"""
import argparse
import base64
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def read(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--project", default="")
    ap.add_argument("--credit", default="")
    ap.add_argument("--timing", default="planner")
    ap.add_argument("--currency", default="")
    a = ap.parse_args()
    m = json.load(open(a.model, encoding="utf-8"))
    m["project"], m["credit"], m["timing"] = a.project, a.credit, a.timing
    if a.currency:
        m["currency"] = a.currency
    b = base64.b64encode(gzip.compress(open(os.path.join(os.path.dirname(a.model), "model.bin"), "rb").read(), 9)).decode()
    html = read("viewer_template.html")
    html = html.replace("/*THREE*/", read("vendor/three.min.js") + "\n" + read("vendor/OrbitControls.js"))
    data = json.dumps(m, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("/*DATA*/", "window.M=" + data + ";window.BIN='" + b + "';")
    open(a.out, "w", encoding="utf-8").write(html)
    print(a.out, round(os.path.getsize(a.out) / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
