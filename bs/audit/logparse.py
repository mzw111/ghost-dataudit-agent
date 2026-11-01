"""Generic parser for the heterogeneous log layouts found in dataset/evidence/logs.

Every line is normalised to dict(ts, level, service, trace, event, kv).
Layouts handled: key=value, JSON-structured, RFC5424-ish syslog, bracketed
application trace, pipe-delimited stream and cloud-runtime (escaped message).
"""
import json
import re

TS = r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
KV = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=(?:"((?:[^"\\]|\\.)*)"|(\S+))')


def parse_kv(text):
    out = {}
    for m in KV.finditer(text):
        v = m.group(2) if m.group(2) is not None else m.group(3)
        out[m.group(1)] = v
    return out


def parse_line(line):
    line = line.rstrip("\n")
    m = re.match(TS + r"\s+(.*)$", line)
    if not m:
        return None
    ts, rest = m.group(1), m.group(2)
    # JSON structured
    if rest.startswith("{"):
        try:
            d = json.loads(rest)
        except ValueError:
            return None
        kv = {k: ("" if v is None else str(v)) for k, v in d.items()}
        return dict(ts=ts, level=kv.pop("severity", ""), service=kv.pop("service", kv.get("logger", "")),
                    trace=kv.pop("trace_id", ""), event=kv.pop("event", ""), kv=kv)
    # cloud runtime export
    if rest.startswith("requestId="):
        outer = parse_kv(rest.split(" message=", 1)[0])
        msg = rest.split(" message=", 1)[1].strip()
        if msg.startswith('"') and msg.endswith('"'):
            msg = msg[1:-1]
        msg = msg.replace('\\"', '"').replace("\\\\", "\\")
        kv = parse_kv(msg)
        return dict(ts=ts, level=outer.get("level", ""), service=outer.get("function", ""),
                    trace=outer.get("requestId", ""), event=kv.pop("event", ""), kv=kv)
    # syslog: <15>1 node service trace - - kv...
    m = re.match(r"<\d+>1\s+(\S+)\s+(\S+)\s+(\S+)\s+-\s+-\s+(.*)$", rest)
    if m:
        kv = parse_kv(m.group(4))
        return dict(ts=ts, level=kv.pop("level", ""), service=m.group(2), trace=m.group(3),
                    event=kv.pop("event", ""), kv=kv)
    # bracketed app trace
    m = re.match(r"\[(\w+)\]\s+\[([^\]]*)\]\s+\[([^\]]*)\]\s+([A-Za-z0-9_]+):\s*(.*)$", rest)
    if m:
        return dict(ts=ts, level=m.group(1), service=m.group(2), trace=m.group(3), event=m.group(4),
                    kv=parse_kv(m.group(5)))
    # pipe stream
    if " | " in rest:
        parts = [p.strip() for p in rest.split(" | ", 4)]
        if len(parts) == 5:
            return dict(ts=ts, level=parts[0], service=parts[1], trace=parts[2], event=parts[3],
                        kv=parse_kv(parts[4]))
    # plain key=value
    kv = parse_kv(rest)
    lvl = rest.split()[0] if rest.split() and "=" not in rest.split()[0] else kv.pop("level", "")
    return dict(ts=ts, level=lvl, service=kv.pop("service", ""), trace=kv.pop("trace_id", kv.pop("seq", "")),
                event=kv.pop("event", ""), kv=kv)


def parse_file(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            r = parse_line(ln)
            if r:
                rows.append(r)
    return rows
