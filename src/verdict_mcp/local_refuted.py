"""Claims the code already answers, set aside before they are filed.

A small model reading one function at a time makes two kinds of claim over and over that a fact
this run already holds answers:

- **A compile error in code a passing gate compiled.** The model saw one function and read a type
  or a name declared elsewhere as a mistake. The build gate compiled all of it, and passed.
- **A null dereference of a member the project declares non-null.** In a C# project that enables
  nullable reference types, a property declared `string Name { get; set; } = "";` or a positional
  record parameter `string Name` is non-null by the code's own statement, which the compiler checks
  at every assignment. Shown only the function, the model claims it can be null.

Measured 2026-11-20 on a .NET and React product's three local runs on `chat-120b`: of 200 claims,
89 were checked by reading, and about three in four were false or described the design. The two
commonest false kinds were these.

A claim set aside is not lost. `check` returns the decision as a plain value, with the fact that
answers the claim, or None to file it. `file_findings` keeps every decision; the run writes them to
`facts.json` as `set_aside`, and the report lists them.

What the null rule leaves alone, because a declaration does not answer it:
- a claim that a nullable value flows into a non-null member (`nullable` in its words): the
  compiler only warns there, and a build that allows warnings still passes;
- a claim about a value from outside the code: deserialized JSON, a request body, `null!`,
  `default(...)`, reflection;
- a member of a type bound from a request (an action's parameter, `[FromBody]`, a minimal-API
  handler's parameter) or reachable from one, since JSON can set any of its properties to null;
- a property with no initializer, or one initialized to `null!` or `default!`: it is null until
  something sets it.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    from . import languages
    from .gitenv import git_env
    from .local_chunks import language_note
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import languages
    from gitenv import git_env
    from local_chunks import language_note


COMPILED = "compiled"
DECLARED = "declared-non-null"


# ── a compile error a passing gate answers ────────────────────────────────────

_COMPILE_CLAIM = re.compile(
    r"\b(?:compile|compiler|compilation)(?:[- ]time)?[- ](?:error|failure)s?\b"
    r"|\b(?:fails?|failing) to compile\b"
    r"|\b(?:does not|doesn't|do not|don't|won't|will not|would not|cannot|can't|could not) compile\b"
    r"|\b(?:CS|TS)\d{4}\b", re.I)

# The commands that compile each language. A gate line is read step by step (split on `&&`, `||`,
# `;` and `|`), so `dotnet build … && dotnet test --no-build` still compiles, and a lone
# `dotnet test --no-build` does not.
_JVM = re.compile(r"\b(?:gradlew?|mvnw?)\b.*\b(?:build|compile\w*|test|check|assemble|package|verify|"
                  r"install)\b")
_COMPILERS = {
    "csharp": re.compile(r"\bdotnet\s+(?:build|test|publish|run|pack)\b|\bmsbuild\b", re.I),
    "typescript": re.compile(r"\b(?:vue-)?tsc\b|\btype-?check\b", re.I),
    "go": re.compile(r"\bgo\s+(?:build|vet|test)\b"),
    "rust": re.compile(r"\bcargo\s+(?:build|check|test|clippy)\b"),
    "java": _JVM,
    "kotlin": _JVM,
    "swift": re.compile(r"\bswift\s+(?:build|test)\b|\bxcodebuild\b"),
    "dart": re.compile(r"\b(?:dart|flutter)\s+(?:analyze|test|build)\b"),
}
_NO_BUILD = re.compile(r"--no-build\b")
_STEP = re.compile(r"&&|\|\||;|\|")
_CD = re.compile(r"\bcd\s+['\"]?([^\s'\";&|]+)")
_PROJECT_FILE = re.compile(r"([\w./-]+)\.(?:csproj|fsproj|vbproj)\b")


def _under(rel: str, folder: str) -> bool:
    folder = folder.strip().strip("/").removeprefix("./")
    return folder in ("", ".") or rel == folder or rel.startswith(folder + "/")


def compiling_gate(gates: dict, lang: str, rel: str) -> str | None:
    """The name of a gate this run passed that compiled `rel`, or None.

    A gate that changes into a folder (`cd web && npx tsc`) compiles that folder, and one that
    names a project file compiles that project's folder; anything else is taken to compile the
    whole checkout."""
    pattern = _COMPILERS.get(lang)
    if pattern is None:
        return None
    for name, gate in sorted((gates or {}).items()):
        if not isinstance(gate, dict) or gate.get("exit_code") != 0:
            continue
        command = str(gate.get("command") or "")
        steps = [s for s in _STEP.split(command) if pattern.search(s) and not _NO_BUILD.search(s)]
        if not steps:
            continue
        where = _CD.search(command)
        if where and not _under(rel, where.group(1)):
            continue
        project = next((m for m in map(_PROJECT_FILE.search, steps) if m), None)
        if project and not _under(rel, str(Path(project.group(1)).parent)):
            continue
        return name
    return None


# ── a null a declaration answers ──────────────────────────────────────────────

_DEREFERENCE = re.compile(
    r"NullReferenceException|ArgumentNullException|\bNRE\b|\bnull (?:dereference|reference)\b"
    r"|\b(?:is|are|be|being|been|was|were|returns?|returning)\s+null\b", re.I)
_FLOW = re.compile(r"\b(?:non-?)?nullable\b", re.I)       # read in the title only
_RETURNS = re.compile(r"\b(?:returns?|returning)\s+null\b", re.I)  # a method's result: no declaration
_OUTSIDE = re.compile(r"deserializ|\bjson\b|request body|\bpayload\b|null!|\bdefault\(|reflection", re.I)
# What the claim says is null, in the forms such a model writes it: `x.Member is null`, `Member may
# be null`, `null Member`, `null checks on A and B`. A lower-case subject is a parameter or a local,
# which no member declaration answers.
_CHAIN = r"([A-Za-z_][\w.?()]*)"
_IS_NULL = re.compile(_CHAIN + r"\s+(?:(?:may|might|can|could|will|would|should)\s+)?"
                      r"(?:is|are|was|were|be|being|been)\s+null\b", re.I)
_NULL_THING = re.compile(r"(?i:\bnull)\s+`?([A-Z]\w*(?:\.[A-Z]\w*)*)`?(?!\s*\()")
_CHECKS_ON = re.compile(r"\bnull[- ]checks?\s+(?:on|for)\s+`?" + _CHAIN + r"`?(?:\s+(?:and|or)\s+`?" + _CHAIN + r"`?)?",
                        re.I)
_DOTTED = re.compile(r"\b[A-Za-z_]\w*\??\.([A-Z]\w*)\b(?!\s*\()")
_TICKED = re.compile(r"`([A-Z]\w*)`(?!\s*\()")
_HUMPED = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+)\b(?!\s*\()")
# A parameter of these kinds is a service the framework injects, not something a request carries.
_SERVICE = re.compile(r"^I[A-Z]|(?:Service|Store|Registry|Provider|Issuer|Validator|Throttle|Factory|"
                      r"Logger|Client|Repository|Cache|Clock|Writer|Handler|Manager|Accessor)$")

_TYPE_HEAD = re.compile(
    r"^[ \t]*(?:\[[^\]\n]*\][ \t]*)*(?:(?:public|internal|private|protected|static|sealed|abstract|"
    r"partial|readonly|file|unsafe|new|ref)\s+)*(?:class|struct|interface|enum|"
    r"record(?:\s+(?:class|struct))?)\s+([A-Za-z_]\w*)", re.M)
_PROPERTY = re.compile(
    r"^[ \t]*(?:\[[^\]\n]*\][ \t]*)*((?:(?:public|internal|protected|private|static|virtual|override|"
    r"sealed|new|required)\s+)+)([A-Za-z_][\w.<>,\[\] ]*?\??)\s+([A-Z]\w*)\s*\{[^{}\n]*\}"
    r"(?:\s*=\s*([^;\n]+);)?", re.M)
_RECORD = re.compile(r"\brecord(?:\s+(?:class|struct))?\s+([A-Za-z_]\w*)\s*(?:<[^>()]*>)?\s*\(([^)]*)\)")
# Any member declaration line, whatever its shape (a field, an expression-bodied or multi-line
# property, a method): the names `_PROPERTY` captured must account for every one of them before
# "every declaration of this name" means anything.
_ANY_MEMBER = re.compile(
    r"^[ \t]*(?:\[[^\]\n]*\][ \t]*)*(?:(?:public|internal|protected|private|static|readonly|virtual|"
    r"override|sealed|new|required|const|abstract|async|extern|volatile)\s+)+[\w.<>,\[\]? ]*?([A-Z]\w*)"
    r"\s*(?=[;={(]|=>|$)", re.M)
_NULL_INIT = re.compile(r"^\s*(?:null|default)\b")
_ACTION = re.compile(
    r"\[(?:Http(?:Get|Post|Put|Patch|Delete)|Route|AcceptVerbs)\b[^\]]*\]\s*(?:\[[^\]]*\]\s*)*"
    r"(?:(?:public|internal|protected|private|static|async|virtual|override)\s+)+[^(;{=]*?\w+\s*\(([^)]*)\)")
_FROM = re.compile(r"\[From(?:Body|Form|Query|Route)\]\s*([A-Za-z_][\w.<>]*)")
_MAPPED = re.compile(r"\.Map(?:Get|Post|Put|Patch|Delete|Methods)\s*\([^;]*?\(([^)]*)\)\s*=>", re.S)
_IDENT = re.compile(r"\b([A-Z]\w*)\b")


def _params(text: str) -> list:
    """`Type name` pairs of a parameter list, split at commas outside `<…>`, `[…]` and `(…)`, with
    attributes and default values dropped."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "<[(":
            depth += 1
        elif ch in ">])":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    out = []
    for part in parts:
        part = re.sub(r"\[[^\]]*\]", " ", part).split("=", 1)[0].strip()
        bits = part.split()
        if len(bits) >= 2:
            out.append((" ".join(bits[:-1]), bits[-1]))
    return out


class Declarations:
    """Every C# property and positional record parameter the checkout declares: whether each is
    non-null, where, and in which type; and which types a request binds."""

    def __init__(self, repo: Path):
        self.members: dict = {}           # name -> [(non_null, rel, line, text, owner, type)]
        self.by_owner: dict = {}          # (owner, name) -> the same tuples
        self.lines: dict = {}             # name -> member declaration lines of any shape
        self.properties: dict = {}        # name -> how many of those `_PROPERTY` read
        self.types: set = set()
        self.bound: set = set()
        proc = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--", "*.cs"],
                              capture_output=True, env=git_env())
        names = proc.stdout.decode("utf-8", "replace").split("\0") if proc.returncode == 0 else []
        roots: set = set()
        for rel in (n for n in names if n and not languages.is_generated(n)):
            try:
                text = (Path(repo) / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            heads = [(m.start(), m.group(1)) for m in _TYPE_HEAD.finditer(text)]
            self.types.update(name for _, name in heads)
            for m in _PROPERTY.finditer(text):
                modifiers, kind, name, init = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
                non_null = not kind.endswith("?") and (
                    (init is not None and not _NULL_INIT.match(init)) or "required" in modifiers.split())
                owner = next((n for at, n in reversed(heads) if at < m.start()), "")
                self._add(name, non_null, rel, text, m.start(), m.group(0).strip(), owner, kind)
                self.properties[name] = self.properties.get(name, 0) + 1
            for m in _ANY_MEMBER.finditer(text):
                self.lines[m.group(1)] = self.lines.get(m.group(1), 0) + 1
            for m in _RECORD.finditer(text):
                for kind, name in _params(m.group(2)):
                    self._add(name, not kind.endswith("?"), rel, text, m.start(), f"record {m.group(1)}(… {kind} {name} …)",
                              m.group(1), kind)
            for m in [*_ACTION.finditer(text), *_MAPPED.finditer(text)]:
                roots.update(_IDENT.findall(" ".join(kind for kind, _ in _params(m.group(1)))))
            roots.update(m.group(1).split("<")[0] for m in _FROM.finditer(text))
        self.bound = self._reachable({t for t in roots & self.types if not _SERVICE.search(t)})

    def _add(self, name, non_null, rel, text, at, said, owner, kind):
        line = text.count("\n", 0, at) + 1
        decl = (non_null, rel, line, said[:120], owner, kind)
        self.members.setdefault(name, []).append(decl)
        self.by_owner.setdefault((owner, name), []).append(decl)

    def _reachable(self, roots: set) -> set:
        """The request-bound types and every type of this checkout their members hold."""
        bound, todo = set(), list(roots)
        while todo:
            owner = todo.pop()
            if owner in bound:
                continue
            bound.add(owner)
            for decls in self.members.values():
                for *_rest, of, kind in decls:
                    if of == owner:
                        todo.extend(t for t in _IDENT.findall(kind) if t in self.types and t not in bound)
        return bound

    def non_null(self, name: str, owner: str | None = None):
        """The declaration that makes `name` non-null, or None when any declaration it could mean
        is nullable, uninitialized, or on a type a request binds. With `owner`, only that type's
        declaration counts; without, every declaration of the name does."""
        decls = self.by_owner.get((owner, name)) if owner else None
        if not decls:
            if self.lines.get(name, 0) > self.properties.get(name, 0):
                return None         # a declaration of the name in a shape not read: a field, `=>`, …
            decls = self.members.get(name) or []
        if not decls or any(not ok or of in self.bound for ok, _r, _l, _t, of, _k in decls):
            return None
        return decls[0], len(decls)


class Refuter:
    """For one claim: the fact this run holds that answers it, or None."""

    def __init__(self, repo: Path, gates: dict | None):
        self.repo, self.gates, self._declarations = Path(repo), gates or {}, None

    def check(self, claim: dict, chunk) -> dict | None:
        text = f"{claim.get('title') or ''} {claim.get('mechanism') or ''}"
        if _COMPILE_CLAIM.search(text):
            gate = compiling_gate(self.gates, chunk.lang, chunk.path)
            if gate:
                return _aside(claim, chunk, COMPILED,
                              f"a compile error, in code the gate `{gate}` compiled and passed this run")
        title = str(claim.get("title") or "")
        if (chunk.lang == "csharp" and _DEREFERENCE.search(title) and not _FLOW.search(title)
                and not _RETURNS.search(text) and not _OUTSIDE.search(text)
                and language_note(self.repo, chunk.path, "csharp")):
            found = self._declared(text, title, chunk)
            if found:
                name, ((_ok, rel, line, said, _owner, _kind), count) = found
                others = (f", and so are the {count - 1} other declaration(s) of the name"
                          if count > 1 else "")
                return _aside(claim, chunk, DECLARED,
                              f"`{name}` is declared non-null, with nullable reference types on: "
                              f"{rel}:{line} `{said}`{others}")
        return None

    def _declared(self, text: str, title: str, chunk):
        """The member the claim says is null and the declaration that answers it, or None. Every
        member it names must be answered; one it cannot place keeps the claim. A claim that says
        what is null (`x.Member is null`) is read whole; one that does not is read by its title
        only, because its explanation quotes code (`word.Length`) whose members are not the claim."""
        if self._declarations is None:
            self._declarations = Declarations(self.repo)
        known = self._declarations
        own = chunk.name.rsplit(".", 1)[-1]
        subjects = [s for m in [*_IS_NULL.finditer(text), *_NULL_THING.finditer(text),
                                *_CHECKS_ON.finditer(text)] for s in m.groups() if s]
        if subjects:
            pairs = [p for p in map(_split, dict.fromkeys(subjects)) if not p[1].endswith("Exception")]
        else:
            named = [n for n in dict.fromkeys(_DOTTED.findall(title) + _TICKED.findall(title))
                     if not n.endswith("Exception") and n != own]
            named = named or [n for n in dict.fromkeys(_HUMPED.findall(title))
                              if not n.endswith("Exception") and n != own and n in known.members]
            pairs = [(None, n) for n in named]
        if not pairs or any(not member[:1].isupper() for _r, member in pairs):
            return None
        found = [(member, known.non_null(member, self._owner(receiver, chunk)))
                 for receiver, member in pairs]
        if any(decl is None for _n, decl in found):
            return None
        return found[0]

    def _owner(self, receiver: str | None, chunk) -> str | None:
        """The type a receiver names (`Ticket.X`), or the type the function or its file declares it
        with (`Ticket ticket`), or None."""
        if not receiver:
            return None
        types = self._declarations.types
        if receiver in types:
            return receiver
        typed = re.compile(r"\b([A-Z]\w*)(?:<[^<>()]*>)?\??\s+" + re.escape(receiver) + r"\b")
        for text in (getattr(chunk, "source", "") or "", _read(self.repo / chunk.path)):
            found = typed.search(text)
            if found and found.group(1) in types:
                return found.group(1)
        return None


def _split(chain: str) -> tuple:
    """`ticket.AssignedTo` → ("ticket", "AssignedTo"); `DeviceNow().Status` → (None, "Status"): a
    call's result has no declared type here."""
    parts = [p for p in chain.replace("?", "").split(".") if p]
    member = re.sub(r"\(.*$", "", parts[-1]) if parts else ""
    receiver = parts[-2] if len(parts) >= 2 and "(" not in parts[-2] else None
    return receiver, member


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _aside(claim: dict, chunk, rule: str, why: str) -> dict:
    return {"path": chunk.path, "line": claim.get("line"), "function": chunk.name,
            "title": claim.get("title"), "severity": claim.get("severity"), "rule": rule, "why": why}
