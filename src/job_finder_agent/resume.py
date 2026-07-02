import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESUME_DIR = PROJECT_ROOT / "data" / "resume"
# Folders scanned for a resume, in priority order.
RESUME_DIRS = (RESUME_DIR, PROJECT_ROOT / "src" / "resume")
SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown"}


def resolve_resume_path(path: str | None = None) -> Path | None:
    """Resolve which resume file to read.

    Priority: explicit path argument -> RESUME_PATH env -> newest supported file
    in data/resume/.
    """
    if path:
        return Path(path)

    env_path = os.getenv("RESUME_PATH", "").strip()
    if env_path:
        return Path(env_path)

    candidates = [
        item
        for directory in RESUME_DIRS
        if directory.exists()
        for item in directory.iterdir()
        if item.is_file()
        and item.suffix.lower() in SUPPORTED_SUFFIXES
        and item.stem.lower() != "readme"
    ]
    if candidates:
        return max(candidates, key=lambda item: item.stat().st_mtime)

    return None


def read_resume(path: str | None = None) -> str:
    """Read a resume file (PDF/TXT/MD) into plain text.

    Drop your resume into data/resume/ or set RESUME_PATH. PDFs are parsed with
    pdfplumber; text/markdown files are read directly.
    """
    resume_path = resolve_resume_path(path)
    if resume_path is None or not resume_path.exists():
        raise FileNotFoundError(
            "No resume found. Put a PDF/TXT/MD file in data/resume/ or set "
            "RESUME_PATH in your .env."
        )

    suffix = resume_path.suffix.lower()
    if suffix == ".pdf":
        text = _read_pdf(resume_path)
    elif suffix in {".txt", ".md", ".markdown"}:
        text = resume_path.read_text(encoding="utf-8", errors="replace")
    else:
        raise ValueError(
            f"Unsupported resume format: {suffix}. Use PDF, TXT, or Markdown."
        )

    text = text.strip()
    if not text:
        raise ValueError(f"Resume at {resume_path} appears to be empty or unreadable.")
    return text


def _read_pdf(resume_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError(
            "Reading PDF resumes requires pdfplumber. Install it with "
            "`uv add pdfplumber`."
        ) from exc

    pages: list[str] = []
    with pdfplumber.open(resume_path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)
