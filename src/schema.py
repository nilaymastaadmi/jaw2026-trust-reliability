"""Route a question by matching it against the DATA MODEL, not against a word list.

WHY THIS EXISTS
---------------
`generic.py` chose a table and a column with hand-written regexes -- one per
entity, one per column. That works exactly as far as the list has been extended
and no further, so every unanticipated question needs a new pattern. It is
memorisation with extra steps, and it cannot generalise to a corpus or a
question nobody has read.

But the vocabulary a question uses is already in the data. The store holds ~23
tables; each has column NAMES that are English words (`guarantee_pct`,
`net_claimed`, `valid_until`), and the categorical columns hold VALUES that
questions quote verbatim (`Kalinga National Bank`, `Bridges & Flyovers`,
`Special Projects Division`). Matching the question against that schema needs
no list at all, and it keeps working when the corpus changes.

HOW
---
The same rarity weighting that already resolves client names, applied to the
whole model:

  * A term is a token of a table name, a token of a column name, or a value of
    a categorical column.
  * A term appearing in many tables says little; one appearing in a single
    table identifies it. Weight is 1/(tables containing the term).
  * A table scores the summed weight of the terms the question mentions. The
    best-scoring table wins, and within it the best-scoring column.

`valid_until` and `validity` and `valid for` all reduce to the stem `valid`, so
the question does not have to use the column's exact spelling.

This runs ONLY where every named shape has already returned nothing, so it can
add coverage and cannot displace a tested answer.
"""
import re
from collections import defaultdict

# Words too common to carry information about which table is meant.
_STOP = {
    "the", "a", "an", "of", "for", "in", "on", "at", "to", "and", "or", "is",
    "are", "was", "were", "be", "been", "what", "which", "how", "many", "much",
    "do", "does", "did", "we", "our", "us", "you", "i", "it", "that", "this",
    "there", "their", "them", "please", "give", "tell", "confirm", "value",
    "total", "amount", "number", "count", "per", "as", "by", "with", "from",
    "have", "has", "had", "no", "not", "any", "all", "each", "some", "one",
    "two", "year", "years", "date", "dates", "doc", "id", "name", "names",
}


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", str(text).lower())
            if t not in _STOP and len(t) > 2]


# Words that appear in a stored value but not in the way a question writes it,
# or the other way round. Dropped from both sides before a run is compared.
_JOIN = {"and", "the", "of", "a", "for", "in", "on", "to", "epc", "b", "net"}


def _run_in(hay, needle):
    return bool(needle) and any(hay[i:i + len(needle)] == needle
                                for i in range(len(hay) - len(needle) + 1))


def _stem(w):
    # -ies folds back to -y rather than being cut off, so that a column called
    # `body` and a question saying "certification bodies" reduce to the same
    # thing. Cutting gave "bod" against "body" and the two never met.
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


class Schema:
    """A term index over every table, column and categorical value in the store."""

    # Columns that are identifiers rather than descriptions: matching a
    # question against every document id would drown the real signal.
    SKIP_COLS = {"doc", "rows", "items", "bills", "audits", "units",
                 "credential_names", "categories_led"}
    # Above this many distinct values a column is treated as free text and only
    # its NAME is indexed, not its contents.
    MAX_VALUES = 400

    def __init__(self, entities):
        self.entities = entities
        self.terms = defaultdict(set)          # entity -> {term}
        self.col_terms = defaultdict(dict)     # entity -> col -> {term}, for ranking
        self.col_forms = defaultdict(dict)     # entity -> col -> [{term}, ...] alternatives
        self.values = defaultdict(dict)        # entity -> col -> {value_lower: value}
        self.numeric = defaultdict(set)        # entity -> {numeric column}
        for ent, rows in entities.items():
            if not rows:
                continue
            for t in _tokens(ent.replace("_", " ")):
                self.terms[ent].add(_stem(t))
            cols = {k for r in rows[:200] for k in r}
            # Which columns hold a number. The answer to every question here is
            # a number, so only these can be the measured quantity -- a column
            # of strings can be a filter and nothing else.
            self.numeric[ent] = {
                c for c in cols
                if any(isinstance(r.get(c), (int, float))
                       and not isinstance(r.get(c), bool) for r in rows)}
            for col in cols:
                if col in self.SKIP_COLS:
                    continue
                # Both spellings of a compound: the column is `headcount`, the
                # question writes "head-count", and neither should have to know
                # about the other.
                parts = _tokens(col.replace("_", " "))
                # ALTERNATIVE spellings of the same column name, each one a set
                # of terms that must ALL be present for that spelling to count.
                # They are alternatives, not conjuncts: `headcount` is matched
                # by the word "headcount" OR by "head" and "count" together, and
                # requiring every generated form at once -- which is what a
                # single flat set amounts to -- made two of every three columns
                # in the store impossible to name.
                forms = []
                if parts:
                    forms.append({_stem(t) for t in parts})
                if len(parts) == 1 and len(parts[0]) > 6:
                    for i in range(3, len(parts[0]) - 2):
                        a, b = parts[0][:i], parts[0][i:]
                        if len(b) > 2:
                            forms.append({_stem(a), _stem(b)})
                elif len(parts) > 1:
                    forms.append({_stem("".join(parts))})
                ct = set().union(*forms) if forms else set()
                if ct:
                    self.col_forms[ent][col] = forms
                    self.col_terms[ent][col] = ct
                    self.terms[ent] |= ct
                vals = {r.get(col) for r in rows}
                # Short values are indexed too -- wage groups are single
                # letters -- and matched only where their column is named in
                # front of them, which value_hits enforces.
                strs = {v for v in vals if isinstance(v, str) and 0 < len(v) < 60}
                if strs and len(strs) <= self.MAX_VALUES:
                    self.values[ent][col] = {v.lower(): v for v in strs}
        df = defaultdict(int)
        for ent, ts in self.terms.items():
            for t in ts:
                df[t] += 1
        self.weight = {t: 1.0 / c for t, c in df.items()}

    # ------------------------------------------------------------- matching
    def _qstems(self, q):
        return {_stem(t) for t in _tokens(q)}

    def value_hits(self, entity, q, partial=True):
        """[(column, value, start, end)] for every categorical value quoted.

        A value is matched in full where the question quotes it in full, and
        otherwise by a contiguous run of its words -- "contract revenue"
        identifies "Contract Revenue (EPC)" and "bridges and flyovers"
        identifies "Bridges & Flyovers", neither of which any question writes
        the way the store spells it. Connectives and brackets are dropped from
        both sides so the two renderings the corpus itself uses both land.

        The span is returned so the caller can tell an independent mention from
        one sitting INSIDE another: the category "Irrigation" lives inside the
        client "Irrigation & Waterways Dept, Govt of Rajasthan", and filtering
        on both empties the table.
        """
        qw = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in _JOIN]
        out = []
        for col, vals in self.values.get(entity, {}).items():
            best = None
            colwords = [w for w in re.split(r"[_\s]+", col) if len(w) > 2]
            for low, orig in vals.items():
                if len(low) < 4:
                    # A short value is only a mention when its COLUMN is named
                    # right in front of it: "Wage Group B" means the wage group,
                    # a bare "B" means nothing. Skipping them outright lost every
                    # single-letter code in the corpus.
                    if not colwords:
                        continue
                    m = re.search(r"(?<![\w])"
                                  + r"\s*".join(re.escape(w) for w in colwords)
                                  + r"\s*[:\-]?\s*" + re.escape(low) + r"(?![\w])",
                                  q, re.I)
                    if m and (best is None or len(orig) > len(best[0])):
                        best = (orig, m.start(), m.end())
                    continue
                m = re.search(r"(?<![\w])" + re.escape(low) + r"(?![\w])", q, re.I)
                if m is None and partial:
                    vw = [w for w in re.findall(r"[a-z0-9]+", low) if w not in _JOIN]
                    if len(vw) >= 2 and _run_in(qw, vw):
                        m = re.search(r"(?<![\w])" + re.escape(vw[0]) + r"(?![\w])",
                                      q, re.I)
                if m is None:
                    continue
                if best is None or len(orig) > len(best[0]):
                    best = (orig, m.start(), m.end())
            if best:
                out.append((col, best[0], best[1], best[2]))
        # Longest match first, so a column explaining more of the question is
        # given the chance to claim it before a shorter one overlaps it.
        out.sort(key=lambda r: -(r[3] - r[2]))
        return out

    def score_entity(self, entity, q, qs=None):
        """Summed rarity weight of the schema terms this question mentions."""
        qs = qs if qs is not None else self._qstems(q)
        s = sum(self.weight.get(t, 0.0) for t in (self.terms[entity] & qs))
        # A quoted VALUE is far stronger evidence than a column name: only one
        # table holds "Kalinga National Bank" or "Bridges & Flyovers".
        s += 2.0 * len(self.value_hits(entity, q))
        return s

    def rank(self, q, allowed=None):
        """[(score, entity)] high to low, over the tables allowed."""
        qs = self._qstems(q)
        out = [(self.score_entity(e, q, qs), e) for e in self.terms
               if allowed is None or e in allowed]
        out.sort(key=lambda r: (-r[0], r[1]))
        return [r for r in out if r[0] > 0]

    def best_column(self, entity, q, exclude=()):
        """The NUMERIC column this question is asking for, or None.

        Two properties of the task do the work here, and without them this
        picks the wrong column more often than it picks the right one:

          * The answer is always a number, so a column of strings cannot be it.
          * A question states its FILTERS and leaves the measured quantity
            implicit -- "for bond BND-00150, how many days between issue and
            expiry" names the bond number and the dates it is measuring
            BETWEEN, none of which is the answer. A column already being used
            to select rows is not the column being asked for.

        And the match has to be nearly complete: a one-word overlap with a
        two-word column name is not evidence, because `date`, `year`, `value`
        and `status` overlap with almost any question ever asked.
        """
        qs = self._qstems(q)
        best, score = None, 0.0
        for col, forms in self.col_forms.get(entity, {}).items():
            if col in exclude or col not in self.numeric.get(entity, ()):
                continue
            # One SPELLING of the name, matched completely. A partial match on
            # a two-word name says nothing: `date`, `year`, `value` and `status`
            # overlap with almost any question ever asked.
            hit = max((f for f in forms if f <= qs), key=len, default=None)
            if not hit:
                continue
            s = sum(self.weight.get(t, 0.0) for t in hit) * len(hit)
            if s > score:
                best, score = col, s
        return best

    def name_column(self, entity, q, exclude=()):
        """The column of `entity` this question NAMES, numeric or not.

        `distinct` needs a column to count the values of, and the question
        always says which -- "how many distinct certification BODIES", "how
        many different project MANAGERS". best_column cannot serve: the column
        wanted here is a column of strings, which is exactly what that one
        rules out.

        Same completeness bar as best_column -- every word of the column's name
        has to be present, so `date` and `year` do not attach themselves to any
        question that happens to mention time.
        """
        qs = self._qstems(q)
        best, score = None, 0.0
        for col, forms in self.col_forms.get(entity, {}).items():
            if col in exclude or col == "doc":
                continue
            hit = max((f for f in forms if f <= qs), key=len, default=None)
            if not hit:
                continue
            s = sum(self.weight.get(t, 0.0) for t in hit) * len(hit)
            if s > score:
                best, score = col, s
        return best
