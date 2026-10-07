"""19 tasks with machine-checkable answers, plus an optional partial-credit state check.

Every task exposes the same surface, which is what lets one search method run on all of them:
  prompt   - the question text
  step     - grades an *intermediate* artifact (may be None: nothing checkable mid-way)
  final    - grades a *complete* answer  -> the pass/fail column of the results table
"""
import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from itertools import combinations


@dataclass
class Task:
    id: str
    kind: str
    prompt: str
    final: object                      # str -> bool
    step: object = None                # str -> bool | None  (partial credit / pruning signal)
    step_hint: str = "partial work so far"
    score: object = None               # str -> bool | None, verifier-based ranking for tree search
    examples: list = field(default_factory=list)


# ---------------------------------------------------------------- game of 24
def _can_reach(nums, target=24.0):
    """Exhaustive check: can these numbers still make the target? This is a real (not model-guessed)
    intermediate verifier, which is the paper's 'value' step done by search instead of by vibes."""
    if len(nums) == 1:
        return abs(nums[0] - target) < 1e-6
    for i, j in combinations(range(len(nums)), 2):
        rest = [n for k, n in enumerate(nums) if k not in (i, j)]
        a, b = nums[i], nums[j]
        for v in (a + b, a - b, b - a, a * b) + ((a / b, b / a) if b and a else ()):
            if _can_reach(rest + [v], target):
                return True
    return False


def _numbers(text):
    return [int(n) for n in re.findall(r"\b\d+\b", text)]


def _remaining(text, start):
    """Replay the model's intermediate equations to see which numbers are left.
    Each operand is removed from the working set, so '(10-4)*...' consumes 10 and 4."""
    nums = list(start)
    for line in text.splitlines():
        if "=" not in line:
            continue
        made = re.search(r"=\s*(-?\d+(?:\.\d+)?)", line)
        left = line.split("=")[0]
        if not made or not re.search(r"[+\-*/]", left):
            continue
        for part in re.split(r"[+\-*/()\s]+", left):
            if part.isdigit() and int(part) in nums:
                nums.remove(int(part))
        nums.append(float(made.group(1)))
    return nums

G24 = [("1 1 4 6", "(1-1)+(4*6)"), ("3 3 8 8", "8/(3-8/3)"), ("4 9 10 13", "(4-10)*(9-13)"),
       ("5 5 5 1", "5*(5-1/5)"), ("2 3 5 12", "12/(3-(5/2))"), ("6 6 6 6", "6+6+6+6"),
       ("1 5 5 5", "5*(5-1/5)"), ("2 7 8 9", "(2*(7+9))-8")]

# ------------------------------------------------------------------- programs
PROGRAMS = [
    ("merge_intervals", "Merge all overlapping intervals and return them sorted by start.\n"
     "merge_intervals([[1,4],[0,2],[3,5]]) -> [[0,5]]",
     "assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]\n"
     "assert merge_intervals([[1,4],[4,5]]) == [[1,5]]\n"
     "assert merge_intervals([[1,4],[0,2],[3,5]]) == [[0,5]]"),
    ("rotate", "Rotate an n x n matrix 90 degrees clockwise IN PLACE, return None.\n"
     "m = [[1,2,3],[4,5,6],[7,8,9]]; rotate(m) -> m == [[7,4,1],[8,5,2],[9,6,3]]",
     "m = [[1,2,3],[4,5,6],[7,8,9]]\n"
     "assert rotate(m) is None\n"
     "assert m == [[7,4,1],[8,5,2],[9,6,3]]\n"
     "assert rotate([]) is None"),
    ("kth_largest", "Return the k-th largest element in the list nums (1-indexed, with duplicates).\n"
     "kth_largest([3,2,1,5,6,4], 2) -> 5",
     "assert kth_largest([3,2,1,5,6,4], 2) == 5\n"
     "assert kth_largest([3,2,3,1,2,4,5,5,6], 4) == 4\n"
     "assert kth_largest([1], 1) == 1"),
    ("parse_formula", "Parse a chemical formula into a dict of counts, supporting nested parentheses.\n"
     "parse_formula('K4(ON(SO3)2)2') -> {'K':4,'O':14,'N':2,'S':4}",
     "assert parse_formula('H2O') == {'H':2,'O':1}\n"
     "assert parse_formula('Mg(OH)2') == {'Mg':1,'O':2,'H':2}\n"
     "assert parse_formula('K4(ON(SO3)2)2') == {'K':4,'O':14,'N':2,'S':4}"),
    ("merge_sorted_arrays", "Merge two sorted lists into one sorted list in O(n+m) without using sort().\n"
     "merge_sorted_arrays([1,3,5],[2,4,6]) -> [1,2,3,4,5,6]",
     "assert merge_sorted_arrays([1,3,5],[2,4,6]) == [1,2,3,4,5,6]\n"
     "assert merge_sorted_arrays([], [1,2]) == [1,2]\n"
     "assert merge_sorted_arrays([1,2],[1,2]) == [1,1,2,2]"),
]

# --------------------------------------------------------------------- letters
LETTERS = [("strawberry", "r", 3), ("raspberry", "r", 3), ("Mississippi", "s", 4),
           ("bookkeeper", "k", 2), ("dreadnought", "r", 2), ("refrigerator", "r", 4)]


def extract_code(text):
    """Pull the code out of a fenced block, tolerating models that add prose around it."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)(?:```|\Z)", text, re.S)
    return (m.group(1) if m else text).strip()


def _run_code(text, name, tests):
    """Exec the model's snippet and run the tests, in a subprocess with a timeout."""
    src = (extract_code(text) + "\n\n" + tests + "\nprint('PASS')\n")
    try:
        p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=10)
        return p.returncode == 0 and "PASS" in p.stdout, (p.stderr.strip().splitlines() or [""])[-1]
    except subprocess.TimeoutExpired:
        return False, "timeout"


def _compiles(text, name):
    """Weak, model-free interim signal: does it even parse and define the right name?"""
    try:
        tree = ast.parse(extract_code(text))
    except SyntaxError:
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name for n in ast.walk(tree))


def _make():
    tasks = []

    for i, (nums, _) in enumerate(G24):
        start = [int(n) for n in nums.split()]
        tasks.append(Task(
            id=f"g24-{i}", kind="math", step_hint="the equations so far",
            examples=[("1 2 3 4", "2 * 3 = 6 (left: 1 4 6)\n6 * 4 = 24 (left: 1 24)\n1 * 24 = 24 (left: 24)\nAnswer: (2*3)*4*1"),
                      ("4 6 8 2", "8 / 4 = 2 (left: 6 2 2)\n6 * 2 = 12 (left: 12 2)\n12 * 2 = 24 (left: 24)\nAnswer: (8/4)*6*2")],
            prompt=f"Use all four numbers {nums}, each exactly once, with + - * / to make 24.\n"
                   f"Write one equation per line like '13 - 9 = 4 (left: 4 4 10)'.\n"
                   f"End with a final line 'Answer: <full expression that equals 24>'.",
            step=lambda t, s=start: _can_reach(_remaining(t, s)),
            score=lambda t, s=start: _can_reach(_remaining(t, s)),
            final=lambda t, e=start: _eq24(t, e)))

    for name, desc, tests in PROGRAMS:
        tasks.append(Task(
            id=f"prog-{name}", kind="program", step_hint="the code so far",
            examples=[("add_one", "Add one to x.", "def add_one(x):\n    return x + 1",
                       "assert add_one(1) == 2")],
            prompt=f"Write a Python function `{name}` that does this:\n{desc}\n"
                   f"Output ONLY one ```python code block defining `{name}`. No tests, no explanation.",
            step=lambda t, n=name: _compiles(t, n),
            final=lambda t, n=name, ts=tests: _run_code(t, n, ts)[0]))

    for i, (word, letter, n) in enumerate(LETTERS):
        tasks.append(Task(
            id=f"count-{word}", kind="writing", step_hint="the inventory so far",
            examples=[("giraffe", "f", "Letters in order: g i r a f f e\nAnswer: 2")],
            prompt=f"Count how many times the letter '{letter}' appears in: {word}\n"
                   f"First list the letters in order on one line: 'Letters in order: ...'\n"
                   f"Then give a final line 'Answer: <number>'.",
            step=lambda t, L=letter: "Letters in order:" in t and len(re.findall(r"[A-Za-z]", t.split("Letters in order:")[1].splitlines()[0])) >= 4,
            final=lambda t, L=letter, n=n: (lambda ns: bool(ns) and ns[-1] == n)(_numbers(t))))

    return tasks


def _eq24(text, expect):
    """Check the 'Answer:' line: exactly 24, using the four given numbers, only + - * / ( ).
    The expression is regex-restricted to digits and operators before eval, so this is safe."""
    lines = [l for l in text.splitlines() if l.lower().lstrip("*# ").startswith("answer:")]
    if not lines:
        return False
    expr = re.sub(r"^[^:]*:", "", lines[-1]).strip().strip("`* ") + " "
    if not re.fullmatch(r"[0-9+*/(). -]+", expr) or "**" in expr:
        return False
    if sorted(int(n) for n in re.findall(r"\d+", expr)) != sorted(expect):
        return False
    try:
        return abs(eval(expr) - 24) < 1e-6  # noqa: S307 - regex-restricted to digits and + - * / ( )
    except (SyntaxError, ZeroDivisionError, TypeError):
        return False


TASKS = _make()
