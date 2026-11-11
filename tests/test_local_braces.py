"""`verdict-local` reading C#, TypeScript and JavaScript: the same bounded questions, honestly held.

Python questions keep their wording, so what the evals measured is still what runs. A brace-language
question names its language, numbers the file's own lines and carries the head of the type around
the function, because the guard on a whole controller is outside every method of it. Nothing read
in those languages can be executed here: no counterfactual is attempted and none of the probe budget
is spent, and the reason a reading stays unproven is written beside it.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import small  # noqa: E402

from test_local_delta import ScriptedModel, delta, git, project  # noqa: E402

MISMATCH = {"verdict": "mismatch", "line": 14,
            "mechanism": "returns the gross total where the doc comment promises the net one"}
REAL = {"is_real": True, "severity": "Major", "title": "Net returns the gross total",
        "impact": "every invoice is overstated by the tax"}

ORDERS = '''namespace Shop;

[Authorize(Policy = "Operator")]
public sealed class Invoices
{
    private const decimal Rate = 0.2m;

    /// <summary>The net total: gross less the tax.</summary>
    public decimal Net(decimal gross)
    {
        if (gross < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(gross));
        }
        return gross;
    }
}
'''


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_csharp_question_names_its_language_lines_and_the_type_around_it(tmp_path):
    write(tmp_path, "src/Invoices.cs", ORDERS)
    (chunk,) = small.chunks_in_range(tmp_path, "src/Invoices.cs", {15})
    assert (chunk.name, chunk.start, chunk.end, chunk.lang) == ("Net", 8, 16, "csharp")
    model = ScriptedModel(replies=[MISMATCH, REAL])
    claim = small.examine(model, chunk)
    first, second = model.prompts
    assert "one C# function" in first and "```csharp\n   8|     /// <summary>" in first
    assert "  15|         return gross;" in first, "the file's own numbers, not the excerpt's"
    assert 'It is declared inside: [Authorize(Policy = "Operator")] public sealed class Invoices' in first
    assert "Judge only what this code shows" in first
    assert "this C# function" in second and "Claim: returns the gross total" in second
    assert claim["line"] == 14 and claim["severity"] == "Major"


def test_python_questions_are_worded_exactly_as_before(tmp_path):
    write(tmp_path, "m.py", 'def rate(w):\n    """Cost per kilo."""\n    return w * 2\n')
    (chunk,) = small.chunks_of(tmp_path, "m.py")
    assert small.contract_question(chunk) == small.CONTRACT_Q.format(path="m.py", source=chunk.numbered())
    assert small.classify_question(chunk, "x") == small.CLASSIFY_Q.format(
        path="m.py", source=chunk.numbered(), mechanism="x")


def test_no_counterfactual_is_tried_on_csharp_and_the_reason_is_kept(tmp_path):
    write(tmp_path, "src/Invoices.cs", ORDERS)
    budget = small.Budget(functions=5, probes=3)
    leads, probes, filed = [], [], []
    examined, proven, disproven = small.file_findings(
        ScriptedModel(replies=[MISMATCH, REAL]), tmp_path, [("src/Invoices.cs", {15})],
        lambda *a, **k: None, tmp_path / "findings", filed, sys.executable, True, budget,
        leads=leads, probes=probes)
    assert (examined, proven, disproven) == (1, 0, 0)
    assert budget.used_probes == 0 and probes == [], "nothing was run, so nothing is on the ledger"
    (lead,) = leads
    assert lead["path"] == "src/Invoices.cs" and lead["function"] == "Net"
    assert lead["why"] == small.NO_PROBE.format(language="C#")


def test_a_mixed_diff_ranks_by_lines_added_not_by_language(tmp_path):
    for rel in ("tools/helper.py", "src/Orders.cs", "web/src/App.tsx", "src/Orders.Tests/OrdersTests.cs",
                "web/src/types.d.ts", "README.md"):
        write(tmp_path, rel, "x\n")
    changed = sorted(["tools/helper.py", "src/Orders.cs", "web/src/App.tsx",
                      "src/Orders.Tests/OrdersTests.cs", "web/src/types.d.ts", "README.md"])
    sizes = {"tools/helper.py": 5, "src/Orders.cs": 50, "web/src/App.tsx": 20,
             "src/Orders.Tests/OrdersTests.cs": 400, "web/src/types.d.ts": 90, "README.md": 300}
    assert small.delta_candidates({}, tmp_path, changed, sizes) == [
        "src/Orders.cs", "web/src/App.tsx", "tools/helper.py"], \
        "the biggest change first, whatever its language; tests, declarations and prose are not read"
    named = {"risk_focus": {"named_files": ["tools/helper.py"]}}
    assert small.delta_candidates(named, tmp_path, changed, sizes)[0] == "tools/helper.py", \
        "a file the profile names outright still goes first"
    write(tmp_path, "tools/test_helper.py", "x\n")
    sizes["tools/test_helper.py"] = 900
    assert small.delta_candidates({}, tmp_path, changed + ["tools/test_helper.py"], sizes)[-1] == \
        "tools/test_helper.py", "a Python test is read after every source file, however large"


def test_a_python_only_diff_is_ranked_exactly_as_before(tmp_path):
    for rel in ("a.py", "b.py", "c.py"):
        write(tmp_path, rel, "x = 1\n")
    sizes = {"a.py": 1, "b.py": 100, "c.py": 50}
    assert small.delta_candidates({}, tmp_path, ["a.py", "b.py", "c.py"], sizes) == ["a.py", "b.py", "c.py"]


def test_changed_lines_come_from_the_diff_in_the_new_files_numbering(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    write(repo, "src/Invoices.cs", ORDERS)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    lines = ORDERS.splitlines()
    lines[14] = "        return gross - gross * Rate;"           # line 15 changed
    del lines[5]                                                  # line 6 deleted
    write(repo, "src/Invoices.cs", "\n".join(lines) + "\n")
    git(repo, "commit", "-qam", "net")
    changed = small.changed_lines_in(repo, f"{base}..HEAD", ["src/Invoices.cs"])
    assert changed == {"src/Invoices.cs": {5, 14}}, "a deletion is marked by the line before it"
    assert small.added_lines(repo, f"{base}..HEAD") == {"src/Invoices.cs": 1}


def test_a_csharp_change_in_a_delta_becomes_a_lead_with_its_reason(tmp_path):
    repo, qa = project(tmp_path)
    write(repo, "src/Invoices.cs", ORDERS)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "invoices")
    model = ScriptedModel(replies=[MISMATCH, REAL])     # the constant asks nothing; the method
    assert delta(repo, qa, model, prove=True) == 0
    leads = json.loads((qa / small.LEADS_FILE).read_text(encoding="utf-8"))["leads"]
    assert [(x["path"], x["function"]) for x in leads] == [("src/Invoices.cs", "Net")]
    assert leads[0]["why"] == small.NO_PROBE.format(language="C#")
    state = json.loads((qa / "state.json").read_text(encoding="utf-8"))
    assert state["verdict"] in ("pass with risks", "fail")
    assert small.READ_NOT_RUN in state["not_tested"]
    assert not list((qa / "findings").glob("*.json")) or all(
        "Invoices" not in p.read_text(encoding="utf-8") for p in (qa / "findings").glob("*.json")), \
        "an unproven reading on a project with a record is a lead, never a finding"


def test_a_file_that_fails_to_parse_still_asks_and_never_raises(tmp_path):
    write(tmp_path, "src/Broken.cs", "public class B {\n    void M( {\n        x = \"unterminated;\n")
    assert isinstance(small.chunks_in_range(tmp_path, "src/Broken.cs", {2, 3}), list)
    assert small.chunks_of(tmp_path, "src/Absent.cs") == []


def test_the_run_reads_csharp_through_the_command_line_seam(tmp_path):
    """The flags a gate uses reach the reader: `--range` with a C#-only diff asks questions."""
    from test_local_gate import branch_repo, gate_run, throwaway_root
    repo, sha_range = branch_repo(tmp_path, extra_files={"Invoices.cs": ORDERS})
    qa = throwaway_root(tmp_path)
    model = ScriptedModel()
    assert gate_run(repo, qa, sha_range, model) == 0
    assert model.calls >= 1 and all("```csharp" in p for p in model.prompts)
    out = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True)
    assert out.returncode == 0


def test_the_projects_own_null_settings_reach_the_question(tmp_path):
    """The code's build settings are its own statement about absent values: a question carries
    them, and a project that declares nothing gets no sentence."""
    write(tmp_path, "src/Shop.csproj", "<Project><PropertyGroup><Nullable>enable</Nullable></PropertyGroup></Project>")
    write(tmp_path, "src/Invoices.cs", ORDERS)
    (chunk,) = small.chunks_in_range(tmp_path, "src/Invoices.cs", {15})
    assert "The project enables nullable reference types" in small.contract_question(chunk)
    write(tmp_path, "legacy/Invoices.cs", ORDERS)
    (plain,) = small.chunks_in_range(tmp_path, "legacy/Invoices.cs", {15})
    assert "nullable" not in small.contract_question(plain)
    write(tmp_path, "web/tsconfig.app.json", '{ "compilerOptions": { "strict": true } }')
    write(tmp_path, "web/src/rate.ts", "export function rate(w: number): number {\n  return w * 2;\n}\n")
    (ts,) = small.chunks_in_range(tmp_path, "web/src/rate.ts", {2})
    assert "strict null checks" in small.contract_question(ts)
