"""Draft a cold email to a professor about a research position.

The hard rule here is that nothing may be invented. A professor who replies to a
fabricated claim about their own paper will notice immediately, and that email is
the only one you get to send. So the draft uses only what the applicant actually
has, and marks anything it cannot know as a bracketed placeholder for them to
fill in - never a plausible-sounding guess.
"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.academic_agent.tracker import _invoke, applicant

SYSTEM = """You draft a cold email from a prospective graduate student to a
professor, asking about research opportunities.

What actually gets a reply: short, specific, and obviously not a mass mail. What
gets deleted: three paragraphs of admiration, a full CV in prose, and anything
that could have been sent to a hundred people.

Hard rules:
- NEVER invent anything. Not a paper title, not a finding, not a course, not a
  claim about the applicant's experience. If the sender did not supply it, it
  does not go in.
- When a specific detail would strengthen the email but you were not given it,
  write a [BRACKETED PLACEHOLDER] saying exactly what to insert. A placeholder is
  honest; a plausible invention gets caught on the reply.
- Use only the applicant facts supplied. Do not upgrade a percentage into a GPA,
  do not add skills, do not describe projects you were not told about.

Structure:
- Subject: under 10 words, specific, naming the term and area.
- 1st paragraph: who they are in one sentence, and the concrete reason they are
  writing to THIS professor.
- 2nd paragraph: the most relevant thing they have actually built or done, with a
  real detail. One paragraph, not a list.
- 3rd paragraph: the ask - is the professor taking students for the stated term,
  and would they be open to a short conversation.
- Sign-off with name and a line for links.

Length: 150-200 words in the body. Anything longer does not get read.

Return GitHub-flavoured Markdown:

**Subject:** ...

<the email body>

---
**Before you send**
3 bullets: what to verify, what to personalise, and what to attach.
"""


def _clean_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text or "")
    return match.group(0) if match else ""


def draft(details: str, professor_email: str = "") -> dict:
    """Draft an outreach email. `details` is whatever is known about the professor."""
    profile = applicant()
    address = professor_email or _clean_email(details)

    response = _invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Applicant facts (use ONLY these):\n{json.dumps(profile, indent=2)}\n\n"
            f"Professor / programme details supplied:\n{details.strip()[:4000]}\n\n"
            "Draft the email. Anything not stated above must be a bracketed "
            "placeholder, not a guess."
        )),
    ])
    return {"to": address, "body": str(response.content).strip()}
