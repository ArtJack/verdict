"""Claims a fact of the run already answers are set aside with that fact, and never filed.

A one-function reading claims compile errors in code the build compiled, and null dereferences of
members the project declares non-null. On a .NET product's three local runs (2026-11-20) these were
the two commonest false claims. Each test builds a small checkout and puts to the rule a claim in
the words such a model uses, and each rule has a case that must leave the claim alone.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp.local_refuted import COMPILED, DECLARED, Refuter, compiling_gate  # noqa: E402
from verdict_mcp.local_summary import set_aside_text  # noqa: E402

from test_local_delta import ScriptedModel, delta, git, project  # noqa: E402

NULLABLE = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><Nullable>enable</Nullable></PropertyGroup></Project>\n'
PLAIN = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup></PropertyGroup></Project>\n'

TICKETS = '''namespace Desk;

public sealed class Ticket
{
    public string AssignedTo { get; set; } = "";
    public string? ResolvedBy { get; set; }
    public string? Closed { get; set; } = "";
    public string Title { get; set; }
    public string Note { get; set; } = null!;
    public required string Site { get; init; }
}

public sealed record Reading(string Device, string? Unit);

public static class Tickets
{
    public static string Owner(Ticket ticket)
    {
        return ticket.AssignedTo.Trim();
    }
}
'''

DESK = SimpleNamespace(path="src/Tickets.cs", lang="csharp", name="Tickets.Owner")


def checkout(tmp_path, files):
    root = tmp_path / "co"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(root, "init", "-qb", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


def claim(title, mechanism=""):
    return {"title": title, "mechanism": mechanism, "line": 19, "severity": "Minor"}


# ── a null the declaration answers ────────────────────────────────────────────

def test_a_null_claim_on_a_member_declared_non_null_is_set_aside_with_its_declaration(tmp_path):
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS})
    aside = Refuter(root, {}).check(claim("NullReferenceException when ticket.AssignedTo is null in Owner"), DESK)
    assert aside["rule"] == DECLARED and aside["path"] == "src/Tickets.cs" and aside["line"] == 19
    assert "`AssignedTo` is declared non-null" in aside["why"]
    assert "src/Tickets.cs:5 `public string AssignedTo { get; set; } = \"\";`" in aside["why"], \
        "the reason cites the declaration, so a reader can check it"
    assert aside["function"] == "Tickets.Owner" and aside["severity"] == "Minor"


def test_the_null_rule_needs_the_projects_own_nullable_setting(tmp_path):
    root = checkout(tmp_path, {"App.csproj": PLAIN, "src/Tickets.cs": TICKETS})
    assert Refuter(root, {}).check(claim("NullReferenceException when ticket.AssignedTo is null"), DESK) is None, \
        "without <Nullable>enable</Nullable> a `string` can hold null, and the declaration says nothing"


def test_only_a_non_null_type_with_a_value_counts_as_declared_non_null(tmp_path):
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS})
    refute = Refuter(root, {}).check
    for member in ("ResolvedBy", "Closed", "Title", "Note", "Unit"):
        assert refute(claim(f"NullReferenceException when x.{member} is null"), DESK) is None, \
            f"{member}: a `?` type, no initializer, or `null!` says it can be null"
    for member in ("Site", "Device"):
        aside = refute(claim(f"NullReferenceException when x.{member} is null"), DESK)
        assert aside and aside["rule"] == DECLARED, f"{member}: `required`, or a record parameter without `?`"


def test_a_declaration_in_a_shape_the_index_cannot_read_keeps_the_claim(tmp_path):
    shapes = ("namespace Desk;\npublic sealed class Visit\n{\n    public string? Site;\n}\n",
              "namespace Desk;\npublic sealed class Visit\n{\n    public string? Site\n    {\n        get; set;\n    }\n}\n",
              "namespace Desk;\npublic sealed class Visit\n{\n    public string? Site => null;\n}\n")
    for i, other in enumerate(shapes):
        root = checkout(tmp_path / str(i), {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS, "src/Visit.cs": other})
        assert Refuter(root, {}).check(claim("NullReferenceException when Site is null"), DESK) is None, \
            f"a field, a multi-line or an expression-bodied `Site` was declared and not read ({i})"
    root = checkout(tmp_path / "plain", {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS})
    aside = Refuter(root, {}).check(claim("NullReferenceException when Site is null"), DESK)
    assert aside["rule"] == DECLARED and "other declaration" not in aside["why"]


def test_a_name_declared_nullable_anywhere_keeps_the_claim_unless_the_receiver_is_typed(tmp_path):
    other = "namespace Desk;\npublic sealed class Visit\n{\n    public string? AssignedTo { get; set; }\n}\n"
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS, "src/Visit.cs": other})
    refute = Refuter(root, {}).check
    assert refute(claim("NullReferenceException when AssignedTo is null"), DESK) is None, \
        "the name alone cannot say which declaration the claim means"
    assert refute(claim("NullReferenceException when visit.AssignedTo is null"), DESK) is None, \
        "a receiver nothing here types is only a name"
    aside = refute(claim("NullReferenceException when ticket.AssignedTo is null"), DESK)
    assert aside["rule"] == DECLARED and "src/Tickets.cs:5" in aside["why"], \
        "`Owner(Ticket ticket)` types the receiver, so Ticket's own declaration decides"
    assert refute(claim("NullReferenceException when Visit.AssignedTo is null"), DESK) is None, \
        "a receiver that is a type name picks that type's declaration: nullable here"


def test_what_the_claim_says_is_null_is_its_subject(tmp_path):
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS})
    refute = Refuter(root, {}).check
    for words in ("Null Site causes ArgumentNullException in Owner",
                  "NullReferenceException in Owner due to missing null checks on Site and Device",
                  "NullReferenceException: ticket.AssignedTo may be null when the desk is empty"):
        assert refute(claim(words), DESK)["rule"] == DECLARED, words
    unclear = claim("NullReferenceException in Owner when the ticket's AssignedTo is unassigned",
                    "calls ticket.AssignedTo.Trim() without string.IsNullOrEmpty(ticket.AssignedTo)")
    assert refute(unclear, DESK)["rule"] == DECLARED, "a method named in the explanation is no member"
    quoted = claim("Owner throws NullReferenceException on a null argument",
                   "dereferences `word` (e.g. `word.Site`) without checking it")
    assert refute(quoted, DESK) is None, \
        "with no subject said, the explanation's quoted code names no member: Site is the string's here"
    assert refute(claim("NullReferenceException when objectId is null"), DESK) is None, \
        "a lower-case subject is a parameter or a local: no member declaration answers it"
    plain = claim("NullReferenceException when ticket.AssignedTo is null",
                  "AssignedTo is not checked before Trim; the author may have meant it as nullable")
    assert refute(plain, DESK)["rule"] == DECLARED, "`nullable` keeps a claim only in its title"


def test_a_member_a_request_binds_is_never_taken_as_non_null(tmp_path):
    api = '''namespace Desk;

public sealed class TicketsController : ControllerBase
{
    [HttpPost("raise")]
    public IActionResult Raise(TicketBody body) => Ok();
}

public sealed class TicketBody
{
    /// <summary>Why the request is raised: the class it holds is checked first.</summary>
    public string Reason { get; set; } = "";
    public Line Detail { get; set; } = new();
}

public sealed class TicketStore
{
    public string Shelf { get; set; } = "";
}

public sealed class Line
{
    public string Text { get; set; } = "";
}

public sealed class Patch
{
    public string Field { get; set; } = "";
}

public sealed class Note
{
    public string Words { get; set; } = "";
}

public static class Endpoints
{
    public static void Map(WebApplication app)
    {
        app.MapPost("/notes", (Note note, IClock clock, TicketStore store) => Results.Ok());
    }

    public static void Apply([FromBody] Patch patch) { }
}
'''
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS, "src/Api.cs": api})
    refute = Refuter(root, {}).check
    for member in ("Reason", "Detail", "Text", "Field", "Words"):
        assert refute(claim(f"NullReferenceException when x.{member} is null"), DESK) is None, \
            f"{member}: JSON can set any property of a request type, or of a type it holds, to null"
    assert refute(claim("NullReferenceException when ticket.AssignedTo is null"), DESK)["rule"] == DECLARED, \
        "a type no request binds keeps its declaration"
    assert refute(claim("NullReferenceException when x.Shelf is null"), DESK)["rule"] == DECLARED, \
        "a handler's injected service is not something a request carries"


def test_claims_a_declaration_does_not_answer_are_left_alone(tmp_path):
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS})
    refute = Refuter(root, {}).check
    for words in (
        "Passing a nullable string means ticket.AssignedTo is null in Owner",       # a flow: compiler warns only
        "ticket.AssignedTo is null when the JSON omits it",                         # from outside the code
        "ticket.AssignedTo is compared case-sensitively",                           # not a null claim
        "NullReferenceException when ticket.AssignedTo or user.Identity is null",   # names an undeclared member
        "NullReferenceException in Owner",                                          # names no member
        "NullReferenceException when AssignedTo returns null",                      # a method's result
    ):
        assert refute(claim(words), DESK) is None, words
    aside_said = claim("Owner compares the owner case-sensitively",
                       "AssignedTo is never null here, but the comparison ignores culture")
    assert refute(aside_said, DESK) is None, "a null claim is one whose title says so"


def test_null_claims_in_other_languages_are_not_touched(tmp_path):
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS})
    for lang in ("python", "typescript", "javascript"):
        chunk = SimpleNamespace(path="src/x", lang=lang, name="f")
        assert Refuter(root, {}).check(claim("NullReferenceException when ticket.AssignedTo is null"), chunk) is None


# ── a compile error a passing gate answers ────────────────────────────────────

BUILD = {"build": {"command": "dotnet build App.sln -c Release", "exit_code": 0}}


def test_a_compile_claim_is_set_aside_only_when_a_gate_that_compiles_passed(tmp_path):
    root = checkout(tmp_path, {"App.csproj": NULLABLE, "src/Tickets.cs": TICKETS})
    words = claim("Assigning a nullable DateTime to AnchoredUtc causes a compile error")
    aside = Refuter(root, BUILD).check(words, DESK)
    assert aside["rule"] == COMPILED and "the gate `build` compiled" in aside["why"]
    failed = {"build": {"command": "dotnet build App.sln", "exit_code": 1}}
    assert Refuter(root, failed).check(words, DESK) is None, "a red build answers nothing"
    no_build = {"tests": {"command": "dotnet test App.sln --no-build", "exit_code": 0}}
    assert Refuter(root, no_build).check(words, DESK) is None, "`--no-build` compiled nothing"
    both = {"ci": {"command": "dotnet build App.sln && dotnet test App.sln --no-build", "exit_code": 0}}
    assert Refuter(root, both).check(words, DESK)["rule"] == COMPILED
    for said in ("Incorrect variable name in string interpolation causes compile error",
                 "The method does not compile: `Seen` is never declared", "error CS0103 at line 4"):
        assert Refuter(root, BUILD).check(claim(said), DESK)["rule"] == COMPILED, said
    assert Refuter(root, BUILD).check(claim("Owner returns the wrong ticket's owner"), DESK) is None, \
        "a green build answers only a claim that the code does not compile"


def test_a_gate_compiles_the_folder_or_the_project_it_names():
    web = {"web": {"command": "bash -lc 'cd web && npx tsc --noEmit'", "exit_code": 0}}
    assert compiling_gate(web, "typescript", "web/src/app.tsx") == "web"
    assert compiling_gate(web, "typescript", "api/src/app.ts") is None, "the gate checked web/ only"
    assert compiling_gate(web, "javascript", "web/src/app.js") is None, "tsc type-checks no JavaScript here"
    typecheck = {"types": {"command": "npm run -s typecheck", "exit_code": 0}}
    assert compiling_gate(typecheck, "typescript", "src/app.ts") == "types"
    api = {"api": {"command": "dotnet build backend/Api/Api.csproj", "exit_code": 0}}
    assert compiling_gate(api, "csharp", "backend/Api/Orders.cs") == "api"
    assert compiling_gate(api, "csharp", "backend/Tools/Seed.cs") is None, "another project was not built"
    windows = {"api": {"command": r"dotnet build backend\Api\Api.csproj", "exit_code": 0}}
    assert compiling_gate(windows, "csharp", "backend/Api/Orders.cs") == "api", \
        "a Windows gate line names the same folder git names with forward slashes"
    assert compiling_gate(windows, "csharp", "backend/Tools/Seed.cs") is None
    assert compiling_gate({"g": {"command": "go test ./...", "exit_code": 0}}, "go", "cmd/x.go") == "g"
    assert compiling_gate({"r": {"command": "cargo check", "exit_code": 0}}, "rust", "src/lib.rs") == "r"
    assert compiling_gate({"k": {"command": "./gradlew build", "exit_code": 0}}, "kotlin", "a/B.kt") == "k"
    assert compiling_gate({"lint": {"command": "npm run lint", "exit_code": 0}}, "typescript", "a.ts") is None
    assert compiling_gate(BUILD, "python", "a.py") is None, "nothing compiles Python"


# ── what the run keeps ────────────────────────────────────────────────────────

MISMATCH = {"verdict": "mismatch", "line": 19,
            "mechanism": "ticket.AssignedTo is dereferenced without a null check"}
REAL = {"is_real": True, "severity": "Major", "title": "NullReferenceException when ticket.AssignedTo is null",
        "impact": "the owner's page fails for an unassigned ticket"}


def test_a_set_aside_claim_is_kept_in_the_run_and_never_filed(tmp_path, capsys):
    repo, qa = project(tmp_path)
    (repo / "App.csproj").write_text(NULLABLE, encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "Tickets.cs").write_text(TICKETS, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "the desk")

    assert delta(repo, qa, ScriptedModel(replies=[MISMATCH, REAL])) == 0
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    (aside,) = facts["set_aside"]
    assert aside["rule"] == DECLARED and aside["path"] == "src/Tickets.cs"
    state = json.loads((qa / "state.json").read_text(encoding="utf-8"))
    assert not any("AssignedTo" in str(f.get("title")) for f in state["findings"]), "never filed"
    leads = json.loads((qa / "leads.json").read_text(encoding="utf-8"))["leads"]
    assert not any("AssignedTo" in str(x.get("title")) for x in leads), "never a lead either"
    report = (qa / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "Set aside — claims a fact of this run already answers (1)" in report
    assert "`AssignedTo` is declared non-null" in report
    assert "1 claim(s) set aside" in capsys.readouterr().err


def test_the_reports_list_of_set_aside_claims_is_capped_and_says_so():
    items = [{"path": f"a{i}.cs", "line": i, "function": "F", "title": "t", "why": "w"} for i in range(30)]
    text = set_aside_text(items)
    assert "(30)" in text and text.count("\n- `") == 25
    assert "… and 5 more, in facts.json `set_aside`" in text
    assert set_aside_text([]) == ""
