"""What a person sees of Verdict inside Claude, before they run it.

On 2026-10-05 the plugin's pages in the Claude app looked broken, for two reasons nothing
in this suite looked at:

* **Every image in the README was an empty "Show Image" box.** The plugin page renders the
  README but does not load images, so the seven badges at the top and the demo picture
  became placeholders — the first screen a new user sees. The status line is plain links now,
  and the README carries no image at all.
* **The agent's description was a wall of run-together words.** Settings → Skills prints
  the frontmatter `description` with its line breaks removed, so a hard-wrapped block read
  "daily delta QAruns" and "requirementschange", followed by three `<example>` blocks
  printed as raw markup. Every description an agent, skill or command shows is one line of
  plain text now.

Both are properties of the files a release ships, so both are checked on every file.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LISTED = (sorted(REPO.glob("agents/*.md")) + sorted(REPO.glob("skills/*/SKILL.md"))
          + sorted(REPO.glob("commands/*.md")))
# Skills cap the description at 1024 characters; the same bound keeps an agent's or a
# command's line readable in the same list.
MAX_DESCRIPTION = 1024
_MARKUP = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")


def description_problems(path: Path) -> list[str]:
    """Why a file's frontmatter description would not show as one clean line, if it would not."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return ["no frontmatter"]
    lines = m.group(1).splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line[len("description:"):].strip()
        problems = []
        if value[:1] in ("|", ">"):
            problems.append("a block scalar: its line breaks are removed when it is shown")
        follow = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt.startswith((" ", "\t")):
                break       # the next key; a blank line can sit inside a block, so it does not end it
            follow.append(nxt)
        while follow and not follow[-1].strip():
            follow.pop()
        if follow:
            problems.append(f"continues over {len(follow)} more line(s)")
        if value[:1] in ('"', "'") and (len(value) < 2 or value[-1] != value[0]):
            problems.append("an unbalanced quote")
        plain = value.strip("\"'")
        if not plain:
            problems.append("empty")
        if _MARKUP.search(" ".join([plain] + follow)):
            problems.append("markup such as <example> that is printed raw")
        if len(plain) > MAX_DESCRIPTION:
            problems.append(f"{len(plain)} characters, over {MAX_DESCRIPTION}")
        return problems
    return ["no description"]


@pytest.mark.parametrize("path", LISTED, ids=lambda p: p.relative_to(REPO).as_posix())
def test_every_listed_description_is_one_clean_line(path):
    assert description_problems(path) == [], path.relative_to(REPO).as_posix()


def test_the_check_sees_the_description_that_broke_the_page(tmp_path):
    """The control: the 0.90.4 shape — a wrapped block with an example — is caught."""
    planted = tmp_path / "agent.md"
    planted.write_text("---\nname: x\ndescription: |\n  Skeptical QA agent for daily delta QA\n"
                       "  runs.\n\n  <example>\n  user: hi\n  </example>\nmodel: inherit\n---\n\nbody\n",
                       encoding="utf-8")
    problems = description_problems(planted)
    assert any("block scalar" in p for p in problems) and any("more line" in p for p in problems)


def test_the_readme_carries_no_images():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    images = [line.strip()[:80] for line in readme.splitlines()
              if re.search(r"!\[[^\]]*\]\(|<img\b", line, re.I)]
    assert images == [], ("the plugin page in Claude shows an image as an empty 'Show Image' "
                          "box — use a text link instead:\n  " + "\n  ".join(images))
