"""DOC-PPP-001 -- the consolidated credentials portfolio.

64 pages listing all 155 works with client, category, value, completion date and
-- uniquely in the corpus -- the contractor's ROLE (Prime / JV Partner) for every
work.  Reference letters carry role too but cover only 132 of the 155, so
role_split questions need this document.

Entries render as:

    40. extradosed BridGe - GUJarat PkG-106
    Client
    National Special Projects Office (Prime)
    Category
    Large Bridges
    Executed Value
    INR 40.00 Cr
    Completed
    December 8, 2012 - Certificate CC/34/2012/106
"""
import re

from normalize import money, parse_date, iso, norm_client, norm_work

_ENTRY = re.compile(r"^\s*(\d{1,3})\.\s+(.{6,90})$")
_ROLE = re.compile(r"\((Prime|JV Partner|Sub-?contractor|Consortium)\)\s*$", re.I)
_LABELS = {"Client", "Category", "Executed Value", "Completed", "Value"}


def parse_portfolio(text):
    """-> [{seq, work, work_key, client, role, category, value, completed}]"""
    lines = [l.rstrip() for l in text.split("\n")]
    starts = []
    for i, line in enumerate(lines):
        m = _ENTRY.match(line)
        # a real entry heading is immediately followed by the Client label
        if m and any(lines[j].strip() == "Client" for j in range(i + 1, min(i + 3, len(lines)))):
            starts.append((i, int(m.group(1)), m.group(2).strip()))

    out = []
    for k, (i, seq, work) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        block = lines[i:end]
        vals = {}
        for j, line in enumerate(block):
            lab = line.strip()
            if lab in _LABELS and lab not in vals:
                for nxt in block[j + 1:j + 3]:
                    if nxt.strip():
                        vals[lab] = nxt.strip()
                        break
        client_raw = vals.get("Client", "")
        rm = _ROLE.search(client_raw)
        role = rm.group(1).title().replace("Jv", "JV") if rm else None
        client = _ROLE.sub("", client_raw).strip()
        out.append({
            "seq": seq,
            "work": work,
            "work_key": norm_work(work),
            "client": norm_client(client),
            "role": role,
            "category": vals.get("Category"),
            "value": money(vals.get("Executed Value") or vals.get("Value")),
            "completed": iso(parse_date(vals.get("Completed", ""))),
        })
    return out
