"""Split a .sql migration file into statements.

The services that apply plain SQL files at startup used to split on every
`;`, which breaks on a semicolon inside a string ('...; ...') and on
DO $$ ... $$ blocks (the idempotent way to add a constraint in Postgres).
This splitter only splits on semicolons outside quotes, dollar-quoted
blocks and `--` comments.
"""
import re

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")


def split_sql(sql: str) -> list[str]:
    statements, buf, i, n = [], [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):  # comment to end of line
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if ch == "'":  # string literal, '' escapes a quote
            j = i + 1
            while j < n:
                if sql[j] == "'" and not sql.startswith("''", j):
                    break
                j += 2 if sql.startswith("''", j) else 1
            buf.append(sql[i:j + 1])
            i = j + 1
            continue
        if ch == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                tag = m.group(0)
                end = sql.find(tag, m.end())
                end = n if end == -1 else end + len(tag)
                buf.append(sql[i:end])
                i = end
                continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    stmt = "".join(buf).strip()
    if stmt:
        statements.append(stmt)
    return statements
