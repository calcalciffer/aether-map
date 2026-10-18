#!/usr/bin/env python3
"""
Producer resource-transfer optimizer for SMALL instances (fewer than ~20 producers).

Model
-----
* N producers with 4 non-negative integer resources (R[p]).
* Each producer picks ONE target and an amount per resource to send, never more
  than it originally owned (0 <= S[p,r] <= R[p,r]). Sending nothing = keeping all.
* Final holdings  F = R - S + (what others send to you).
* Resource #4 can count as half value (--half-last) in every objective.

Method (two levels)
-------------------
OUTER  choose the target of every producer (discrete):
         - exhaustive when (N-1)^N is small (N <= 5 by default),
         - otherwise iterated local search (change one target at a time,
           random "kicks" to escape local optima) within a time budget.
         (A "no target" choice is unnecessary: sending zero == no target.)
INNER  for FIXED targets the final state is linear in the amounts S, so the
       amounts are solved with a proper continuous method:
         - MAX_MIN_RES    -> exact linear program (HiGHS), lexicographic
         - MIN_VARIANCE   -> L-BFGS-B with analytic gradient (convex)
         - BALANCED       -> multi-start L-BFGS-B with analytic gradient
FINAL  the best few target sets are re-solved to INTEGER amounts
       (MILP for MAX_MIN_RES, rounding + integer coordinate polish otherwise).

Usage
-----
  python resource_optimizer.py BALANCED a:10,0,5,2 b:0,9,1,4 c:3,3,3,3
  python resource_optimizer.py MAX_MIN_RES --file producers.csv --half-last --time 30
  python resource_optimizer.py MIN_VARIANCE a:10,0,5,2 b:0,9,1,4 c:3,3,3,3 --ratio 2:1:3
  python resource_optimizer.py --list
  python resource_optimizer.py help      (or -h / --help, or no arguments)

--ratio r1:r2:...  ideal proportions between producers' totals, in the order the
  producers are given (2:1:3 -> first should hold twice the second, third thrice).
  Applies to BALANCED (secondary level) and MIN_VARIANCE; ignored by MAX_MIN_RES.

ADDING A NEW OBJECTIVE
----------------------
Smooth objective (most cases): subclass SmoothObjective, decorate with
@register("CODE"), implement cost(F, grad) and levels(F). That is all: the
inner solver, integer rounding and search come for free.
Special structure (e.g. an LP): subclass Objective and implement score(F),
levels(F) and solve_inner(...). Optionally override initial_targets().
"""
import argparse
import csv
import itertools
import random
import re
import sys
import textwrap
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp, minimize

NRES = 4


class InputError(ValueError):
    """Invalid user input (bad producers, ratio, objective...). Safe to show to users."""


# ----------------------------------------------------------------------------
# Problem data
# ----------------------------------------------------------------------------
class Problem:
    def __init__(self, names, R, weights, ratios=None, milp_time=20.0):
        self.milp_time = milp_time  # seconds allowed per integer MILP solve
        self.names = list(names)
        self.R = np.array(R, dtype=float)
        self.w = np.array(weights, dtype=float)
        self.n = len(self.names)
        self.scale = max(float(self.R.max()), 1.0)
        self.custom_ratio = ratios is not None
        rho = np.ones(self.n) if ratios is None else np.array(ratios, dtype=float)
        # ideal weighted total per producer (the grand total is conserved by transfers)
        self.ideal = (self.R * self.w).sum() * rho / rho.sum()

    def final(self, targets, S):
        """Final holdings for given targets (index per producer) and amounts S."""
        F = self.R - S
        np.add.at(F, np.asarray(targets), S)
        return F


def better(a, b, tol=1e-9):
    """Lexicographic 'a strictly better than b' for score tuples (lower=better)."""
    for x, y in zip(a, b):
        if x < y - tol * (1 + abs(y)):
            return True
        if x > y + tol * (1 + abs(y)):
            return False
    return False


# ----------------------------------------------------------------------------
# Objectives
# ----------------------------------------------------------------------------
REGISTRY = {}


def register(code):
    def deco(cls):
        cls.code = code
        REGISTRY[code] = cls
        return cls
    return deco


class Objective(ABC):
    code = ""
    description = ""

    def __init__(self, prob, sec_weight=0.1):
        self.prob = prob
        self.sec_weight = sec_weight

    @abstractmethod
    def levels(self, F):
        """[(label, value, 'min'|'max'), ...] for reporting."""

    @abstractmethod
    def score(self, F):
        """Tuple, compared lexicographically, LOWER is better."""

    @abstractmethod
    def solve_inner(self, targets, S0=None, integer=False, effort="fast"):
        """Best amounts S (n x 4) for fixed targets."""

    def initial_targets(self):
        """Starting targets for local search: send surplus to complementary producers."""
        p = self.prob
        E = p.R * p.w
        m = E.mean(1, keepdims=True)
        comp = np.maximum(E - m, 0) @ np.maximum(m - E, 0).T
        np.fill_diagonal(comp, -1)
        return tuple(int(i) for i in comp.argmax(1))


class SmoothObjective(Objective):
    """Objective with a differentiable cost: solved by L-BFGS-B + integer polish."""

    @abstractmethod
    def cost(self, F, grad=False):
        """Scalar cost (lower better). With grad=True return (cost, dcost/dF)."""

    def score(self, F):
        return (self.cost(F),)

    def solve_inner(self, targets, S0=None, integer=False, effort="fast"):
        pr, n = self.prob, self.prob.n
        t = np.asarray(targets)
        sc = pr.scale
        bounds = list(zip(np.zeros(n * NRES), (pr.R / sc).ravel()))

        def fun(x):
            S = x.reshape(n, NRES) * sc
            c, dF = self.cost(pr.final(t, S), grad=True)
            dS = (-dF + dF[t]) * sc  # S[p] lowers F[p] and raises F[t[p]]
            return c, dS.ravel()

        starts = [np.zeros((n, NRES)) if S0 is None else S0]
        maxiter = 150
        if effort == "full":
            maxiter = 1000
            rng = np.random.default_rng(0)
            starts += [np.zeros((n, NRES)), pr.R.copy(), pr.R * 0.5]
            starts += [pr.R * rng.random((n, NRES)) for _ in range(3)]
        best = None
        for s in starts:
            r = minimize(fun, (s / sc).ravel(), jac=True, method="L-BFGS-B",
                         bounds=bounds, options=dict(maxiter=maxiter, ftol=1e-12, gtol=1e-9))
            if best is None or r.fun < best.fun:
                best = r
        S = np.clip(best.x.reshape(n, NRES) * sc, 0, pr.R)
        return self.integerize(t, S) if integer else S

    def integerize(self, t, S, max_passes=50):
        pr = self.prob
        S = np.clip(np.rint(S), 0, pr.R)
        cur = self.score(pr.final(t, S))
        idx = [(p, r) for p in range(pr.n) for r in range(NRES)]
        for _ in range(max_passes):
            improved = False
            for p, r in idx:
                for d in (1, -1):
                    v = S[p, r] + d
                    if v < 0 or v > pr.R[p, r]:
                        continue
                    S[p, r] = v
                    sc = self.score(pr.final(t, S))
                    if better(sc, cur, 1e-12):
                        cur, improved = sc, True
                    else:
                        S[p, r] -= d
            if not improved:
                break
        return S


def _stats(F, prob):
    """V = mean squared deviation of producer totals from their ideal share
    (equals the plain variance of totals when no --ratio is given)."""
    E = F * prob.w
    T = E.sum(1)
    return dict(gmin=E.min(), summin=E.min(1).sum(), P=E.std(1).sum(),
                V=((T - prob.ideal) ** 2).mean())


@register("BALANCED")
class Balanced(SmoothObjective):
    description = ("Primary: each producer internally balanced across its 4 resources "
                   "(sum of per-producer std-dev). Secondary: variance of totals "
                   "between producers, or deviation from --ratio shares (weight --sec-weight).")

    def __init__(self, prob, sec_weight=0.1):
        super().__init__(prob, sec_weight)
        s = _stats(prob.R, prob)  # normalise both levels by their starting values
        self.c1 = 1.0 / max(s["P"], 1.0)
        self.c2 = sec_weight / max(s["V"], 1.0)

    def levels(self, F):
        s = _stats(F, self.prob)
        return [("sum of per-producer std of resources (internal imbalance)", s["P"], "min"),
                ("variance of producer totals" + (" (vs ideal ratio)" if self.prob.custom_ratio else ""), s["V"], "min")]

    def cost(self, F, grad=False):
        w = self.prob.w
        E = F * w
        d = E - E.mean(1, keepdims=True)
        var = (d ** 2).mean(1)
        T = E.sum(1)
        dev = T - self.prob.ideal
        c = self.c1 * np.sqrt(var).sum() + self.c2 * (dev ** 2).mean()
        if not grad:
            return c
        dE = self.c1 * d / (NRES * np.sqrt(var + 1e-9))[:, None]
        dE += (self.c2 * 2 * dev / len(T))[:, None]
        return c, dE * w


@register("MIN_VARIANCE")
class MinVariance(SmoothObjective):
    description = ("Minimize the variance of producers' total (weighted) holdings, or their "
                   "deviation from the ideal shares given by --ratio.")

    def __init__(self, prob, sec_weight=0.1):
        super().__init__(prob, sec_weight)
        self.c = 1.0 / max(_stats(prob.R, prob)["V"], 1.0)

    def levels(self, F):
        lab = "variance of producer totals" + (" (vs ideal ratio)" if self.prob.custom_ratio else "")
        return [(lab, _stats(F, self.prob)["V"], "min")]

    def cost(self, F, grad=False):
        w = self.prob.w
        dev = (F * w).sum(1) - self.prob.ideal
        c = self.c * (dev ** 2).mean()
        if not grad:
            return c
        g = (self.c * 2 * dev / len(dev))[:, None]
        return c, g * w

    def initial_targets(self):
        pr = self.prob
        order = np.argsort((pr.R * pr.w).sum(1) - pr.ideal)  # most below ideal first
        return tuple(int(order[0] if order[0] != p else order[1]) for p in range(pr.n))


@register("MAX_MIN_RES")
class MaxMinRes(Objective):
    description = ("Maximize the weakest resource of the weakest producer (exact LP/MILP), "
                   "then the sum of every producer's weakest resource.")

    def levels(self, F):
        s = _stats(F, self.prob)
        return [("weakest resource of the weakest producer", s["gmin"], "max"),
                ("sum of each producer's weakest resource", s["summin"], "max")]

    def score(self, F):
        s = _stats(F, self.prob)
        return (-s["gmin"], -s["summin"])

    def solve_inner(self, targets, S0=None, integer=False, effort="fast"):
        pr, n = self.prob, self.prob.n
        nv = n * NRES
        t = np.asarray(targets)
        wv = np.tile(pr.w, n)
        G = -np.eye(nv)  # F_flat = R_flat + G @ S_flat
        for k in range(n):
            for r in range(NRES):
                G[t[k] * NRES + r, k * NRES + r] += 1
        WG, WR, ub = wv[:, None] * G, wv * pr.R.ravel(), pr.R.ravel()
        opts = {"time_limit": pr.milp_time} if integer else {}
        integ = np.ones(nv) if integer else np.zeros(nv)
        fallback = np.zeros((n, NRES)) if S0 is None else np.clip(S0, 0, pr.R)

        # stage 1: maximise the global weakest weighted resource t
        c = np.zeros(nv + 1)
        c[-1] = -1
        r1 = milp(c, constraints=LinearConstraint(np.hstack([-WG, np.ones((nv, 1))]), -np.inf, WR),
                  integrality=np.append(integ, 0),
                  bounds=Bounds(np.zeros(nv + 1), np.append(ub, np.inf)), options=opts)
        if r1.x is None:
            return fallback
        S1 = np.rint(r1.x[:nv]) if integer else r1.x[:nv]
        tstar = float((WR + WG @ S1).min()) - 1e-7

        # stage 2: keep every producer's weakest >= t*, maximise the sum of weakest
        Mrow = np.zeros((nv, n))
        for p in range(n):
            Mrow[p * NRES:(p + 1) * NRES, p] = 1
        c2 = np.zeros(nv + n)
        c2[nv:] = -1
        r2 = milp(c2, constraints=LinearConstraint(np.hstack([-WG, Mrow]), -np.inf, WR),
                  integrality=np.append(integ, np.zeros(n)),
                  bounds=Bounds(np.append(np.zeros(nv), np.full(n, tstar)),
                                np.append(ub, np.full(n, np.inf))), options=opts)
        x = S1 if r2.x is None else r2.x[:nv]
        S = np.rint(x) if integer else x
        return np.clip(S.reshape(n, NRES), 0, pr.R)


# ----------------------------------------------------------------------------
# Target search
# ----------------------------------------------------------------------------
def search(prob, obj, time_limit, rnd, exhaustive_limit):
    n = prob.n
    cache = {}

    def evaluate(t, S0=None):
        if t not in cache:
            S = obj.solve_inner(t, S0)
            cache[t] = (obj.score(prob.final(t, S)), S)
        return cache[t]

    if (n - 1) ** n <= exhaustive_limit:
        mode = "exhaustive"
        hard_stop = time.time() + 3 * time_limit  # safety net for slow objectives
        for t in itertools.product(*[[q for q in range(n) if q != p] for p in range(n)]):
            if time.time() > hard_stop:
                mode = "exhaustive (cut short by time limit)"
                break
            evaluate(t)
    else:
        mode = "iterated local search"
        deadline = time.time() + time_limit
        cur = obj.initial_targets()
        cur_sc, cur_S = evaluate(cur)
        best = (cur, cur_sc, cur_S)
        while time.time() < deadline:
            improved = True
            while improved and time.time() < deadline:
                improved = False
                moves = [(p, q) for p in range(n) for q in range(n) if q != p and q != cur[p]]
                rnd.shuffle(moves)
                for p, q in moves:
                    if time.time() >= deadline:
                        break
                    cand = cur[:p] + (q,) + cur[p + 1:]
                    sc, S = evaluate(cand, cur_S)
                    if better(sc, cur_sc):
                        cur, cur_sc, cur_S = cand, sc, S
                        improved = True
                        break
            if better(cur_sc, best[1]):
                best = (cur, cur_sc, cur_S)
            kick = list(best[0])  # perturb the best solution and climb again
            for p in rnd.sample(range(n), rnd.randint(2, max(2, n // 3))):
                kick[p] = rnd.choice([q for q in range(n) if q != p])
            cur = tuple(kick)
            cur_sc, cur_S = evaluate(cur, best[2])
    ranked = sorted(cache.items(), key=lambda kv: kv[1][0])
    return mode, len(cache), ranked


def finalize(prob, obj, ranked, top_k):
    """Re-solve the best target sets with INTEGER amounts and keep the best."""
    best = None
    for t, (_, S) in ranked[:top_k]:
        Si = obj.solve_inner(t, S0=S, integer=True, effort="full")
        sc = obj.score(prob.final(t, Si))
        if best is None or better(sc, best[0]):
            best = (sc, t, Si)
    return best


# ----------------------------------------------------------------------------
# Public API (used by the Discord bot and by the CLI below)
# ----------------------------------------------------------------------------
# name + 4 whole numbers, separated by ':' ',' '=' or spaces ("a:10,0,5,2", "a 10 0 5 2")
_ENTRY = re.compile(r"([^\s:;,=]+)\s*[:,=]?\s*(\d+)\s*[,\s]\s*(\d+)\s*[,\s]\s*(\d+)\s*[,\s]\s*(\d+)")
_SEPARATORS = re.compile(r"[\s;,]+")


def parse_producers_text(text):
    """Parse free text such as 'a:10,0,5,2 b:0,9,1,4' (spaces, ';' or newlines between
    producers) into (names, R). Raises InputError with a readable message."""
    names, R = _parse_entries(text)
    check_producers(names, R)
    return names, R


def _parse_entries(text):
    text = (text or "").strip()
    if not text:
        raise InputError("No producers given.")
    names, R, gaps, pos = [], [], [], 0
    for m in _ENTRY.finditer(text):
        gaps.append(text[pos:m.start()])
        pos = m.end()
        names.append(m.group(1))
        R.append([int(m.group(i)) for i in range(2, 6)])
    gaps.append(text[pos:])
    for g in gaps:
        if _SEPARATORS.sub("", g):
            bad = g.strip()[:40]
            raise InputError(f"Could not read `{bad}`. Expected name:r1,r2,r3,r4 with four "
                             f"whole numbers >= 0 per producer.")
    if not names:
        raise InputError("No producers found. Expected name:r1,r2,r3,r4 for each producer.")
    return names, R


def clean_table_text(text):
    """Drop blank lines, '#' comments and a header line (one that is not a producer)."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if lines and not _ENTRY.fullmatch(lines[0].strip()):
        lines = lines[1:]
    return "\n".join(lines)


def check_producers(names, R):
    if len(names) != len(R):
        raise InputError("Names and resources do not match.")
    if len(names) < 2:
        raise InputError("Need at least 2 producers (a lone producer cannot send anything).")
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise InputError(f"Producer names must be unique (repeated: {', '.join(dup)}).")
    for n, r in zip(names, R):
        if len(r) != NRES or any(int(x) != x or x < 0 for x in r):
            raise InputError(f"{n}: need {NRES} non-negative whole numbers.")


def parse_ratio(text, n):
    """'2:1:3' -> [2.0, 1.0, 3.0], one value per producer (input order)."""
    parts = [p for p in re.split(r"[:,\s]+", (text or "").strip()) if p]
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        raise InputError("Ratio must look like 2:1:3 (numbers separated by ':').")
    if len(vals) != n:
        raise InputError(f"Ratio needs one value per producer: expected {n}, got {len(vals)}.")
    if min(vals) < 0 or sum(vals) <= 0 or not all(np.isfinite(vals)):
        raise InputError("Ratio values must be non-negative and not all zero.")
    return vals


@dataclass
class Result:
    objective: str
    names: List[str]
    weights: tuple
    initial: np.ndarray          # (n, 4) ints, holdings before
    final: np.ndarray            # (n, 4) ints, holdings after
    sent: np.ndarray             # (n, 4) ints, what each producer sends
    targets: List[int]           # target index per producer (meaningful if it sends)
    mode: str                    # how targets were searched
    n_evaluated: int
    elapsed: float
    levels: list                 # [(label, before, after, 'min'|'max'), ...]
    ideal: Optional[np.ndarray]  # ideal weighted totals when a ratio was used
    notes: List[str] = field(default_factory=list)
    valid: bool = True           # constraint check passed

    def transfers(self):
        """[(sender_idx, target_idx, amounts list)] for producers that actually send."""
        return [(p, self.targets[p], self.sent[p].tolist())
                for p in range(len(self.names)) if self.sent[p].any()]

    def weighted_total(self, p):
        return float((self.final[p] * np.array(self.weights)).sum())


def optimize(code, names, R, *, half_last=False, ratios=None, sec_weight=0.1,
             time_limit=20.0, seed=None, exhaustive_limit=2000, top_k=5, milp_time=20.0):
    """Run the full search and return a Result. Raises InputError on invalid input.
    CPU-bound and blocking: from async code run it in a thread."""
    code = str(code).upper()
    if code not in REGISTRY:
        raise InputError(f"Unknown objective '{code}'. Available: {', '.join(REGISTRY)}")
    names = [str(n) for n in names]
    R = [[int(x) for x in r] for r in R]
    check_producers(names, R)
    notes = []
    if ratios is not None:
        if len(ratios) != len(names):
            raise InputError(f"Ratio needs one value per producer: expected {len(names)}, "
                             f"got {len(ratios)}.")
        if code == "MAX_MIN_RES":
            notes.append("The ratio is ignored by MAX_MIN_RES.")
            ratios = None
    weights = (1, 1, 1, 0.5) if half_last else (1, 1, 1, 1)
    prob = Problem(names, R, weights, ratios, milp_time)
    obj = REGISTRY[code](prob, sec_weight)
    rnd = random.Random(seed)

    t0 = time.time()
    mode, n_eval, ranked = search(prob, obj, time_limit, rnd, exhaustive_limit)
    _, targets, S = finalize(prob, obj, ranked, top_k)
    S = np.rint(S).astype(int)
    F = prob.final(targets, S)
    valid = bool(np.array_equal(prob.R.sum(0), F.sum(0)) and (F >= 0).all()
                 and (S <= prob.R).all())
    levels = [(lab, b, a, kind) for (lab, b, kind), (_, a, _)
              in zip(obj.levels(prob.R), obj.levels(F))]
    return Result(code, names, tuple(weights), prob.R.astype(int), np.rint(F).astype(int), S,
                  [int(t) for t in targets], mode, n_eval, time.time() - t0, levels,
                  prob.ideal if prob.custom_ratio else None, notes, valid)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def load_producers(args):
    """Producers from positional arguments and/or --file (CSV)."""
    names, R = [], []
    for item in args.producers:
        n, r = _parse_entries(item)
        if len(n) != 1:
            raise InputError(f"Error parsing '{item}': expected one name:r1,r2,r3,r4")
        names += n
        R += r
    if args.file:
        with open(args.file, newline="") as f:
            n, r = _parse_entries(clean_table_text(f.read()))
        names += n
        R += r
    check_producers(names, R)
    return names, R


def print_result(res):
    names = res.names
    print(f"--- Optimization Result: {res.objective} ---")
    print(f"(target search: {res.mode}, {res.n_evaluated} target sets evaluated, "
          f"{res.elapsed:.1f}s)\n")
    print("Movement Plan:")
    for p, name in enumerate(names):
        if res.sent[p].any():
            print(f"  {name} -> {names[res.targets[p]]} | sends {res.sent[p].tolist()}")
        else:
            print(f"  {name} keeps everything")
    print("\nFinal Resource Distribution:")
    for p, name in enumerate(names):
        extra = ""
        if res.ideal is not None:
            extra = f"   total {res.weighted_total(p):.1f} (ideal {res.ideal[p]:.1f})"
        print(f"  {name}: {res.final[p].tolist()}{extra}")
    print("\nObjective levels (before -> after):")
    for lab, b, a, kind in res.levels:
        print(f"  {lab} [{kind}]: {b:.3f} -> {a:.3f}")
    for note in res.notes:
        print(f"Note: {note}")
    print("\nCheck: totals conserved, nobody sent more than owned" if res.valid
          else "\nWARNING: constraint check failed, bug!")


def build_parser():
    objectives = "\n".join(
        textwrap.fill(cls.description, width=78, initial_indent=f"  {c:<13} ",
                      subsequent_indent=" " * 16) for c, cls in REGISTRY.items())
    epilog = f"""\
OBJECTIVES
{objectives}

INPUT
  Producers are given as  name:r1,r2,r3,r4  (4 non-negative integers), either as
  positional arguments or one per line in a CSV file (--file): name,r1,r2,r3,r4
  Names must be unique. Between 2 and 19 producers are expected.

OUTPUT
  A movement plan (who sends what to whom; producers that send nothing "keep
  everything"), the final resources of every producer, and each objective level
  before -> after. Constraints are verified at the end.

HOW IT SEARCHES
  Fixed targets -> amounts are solved exactly/continuously (LP or L-BFGS-B) and
  then made integer. Targets: exhaustive if (N-1)^N <= --exhaustive-limit
  (N <= 5), otherwise iterated local search for --time seconds. For 6+ producers
  the result is a strong heuristic answer, not a proven optimum: raise --time or
  try other --seed values to explore more.

EXAMPLES
  python resource_optimizer.py BALANCED a:10,0,5,2 b:0,9,1,4 c:3,3,3,3
  python resource_optimizer.py MAX_MIN_RES --file producers.csv --half-last --time 30
  python resource_optimizer.py MIN_VARIANCE a:10,0,5,2 b:0,9,1,4 c:3,3,3,3 --ratio 2:1:3
  python resource_optimizer.py --list        (objectives only)
  python resource_optimizer.py help          (this message)
"""
    ap = argparse.ArgumentParser(
        prog="resource_optimizer.py",
        usage="python resource_optimizer.py OBJECTIVE [name:r1,r2,r3,r4 ...] [options]",
        description=textwrap.fill(
            "Choose, for each producer, one target and how much of each of its 4 resources "
            "to send, so that an objective is optimized. A producer can only send what it "
            "originally owned; received resources are not forwarded.", width=78),
        epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code", nargs="?", metavar="OBJECTIVE",
                    help="what to optimize: " + ", ".join(REGISTRY) + " (case-insensitive)")
    ap.add_argument("producers", nargs="*", metavar="name:r1,r2,r3,r4",
                    help="producers given on the command line")
    ap.add_argument("--file", metavar="CSV",
                    help="read producers from a CSV (name,r1,r2,r3,r4 per line; "
                         "'#' comments and one header line allowed); can be combined "
                         "with positional producers")
    ap.add_argument("--half-last", action="store_true",
                    help="resource #4 counts as half value in every objective (balance, "
                         "totals, weakest resource)")
    ap.add_argument("--ratio", metavar="R1:R2:...",
                    help="ideal proportions between producers' totals, in input order "
                         "(2:1:3 -> first holds twice the second, third thrice). Used by "
                         "BALANCED (secondary level) and MIN_VARIANCE; ignored by MAX_MIN_RES. "
                         "A soft target: it is approached as closely as the rules allow")
    ap.add_argument("--sec-weight", type=float, default=0.1, metavar="W",
                    help="BALANCED only: importance of the secondary goal (balance between "
                         "producers) relative to the primary (internal balance). Lower = "
                         "internal balance dominates more (default: %(default)s)")
    ap.add_argument("--time", type=float, default=20, metavar="SEC",
                    help="time budget of the target local search, in seconds; ignored when "
                         "the search is exhaustive (default: %(default)s)")
    ap.add_argument("--seed", type=int, default=None, metavar="N",
                    help="random seed, for reproducible runs (default: random)")
    ap.add_argument("--exhaustive-limit", type=int, default=2000, metavar="K",
                    help="try every target combination when (N-1)^N <= K, otherwise use "
                         "local search (default: %(default)s)")
    ap.add_argument("--top", type=int, default=5, metavar="K",
                    help="how many of the best target sets are re-solved with integer "
                         "amounts; the best of them is reported (default: %(default)s)")
    ap.add_argument("--list", action="store_true", help="list the available objectives and exit")
    return ap


def main():
    ap = build_parser()
    if len(sys.argv) == 1 or sys.argv[1].lower() in ("help", "-help", "/?"):
        ap.print_help()
        return
    args = ap.parse_args()
    if args.list:
        for c, cls in REGISTRY.items():
            print(f"{c:13} {cls.description}")
        return
    try:
        if args.code is None or args.code.upper() not in REGISTRY:
            raise InputError(f"Unknown/missing objective. Available: {', '.join(REGISTRY)}")
        names, R = load_producers(args)
        ratios = parse_ratio(args.ratio, len(R)) if args.ratio else None
        if len(R) >= 20:
            print("Warning: designed for fewer than 20 producers; "
                  "the large-scale annealing version scales better.", file=sys.stderr)
        res = optimize(args.code, names, R, half_last=args.half_last, ratios=ratios,
                       sec_weight=args.sec_weight, time_limit=args.time, seed=args.seed,
                       exhaustive_limit=args.exhaustive_limit, top_k=args.top)
    except InputError as e:
        raise SystemExit(f"Error: {e}")
    print_result(res)


if __name__ == "__main__":
    main()
