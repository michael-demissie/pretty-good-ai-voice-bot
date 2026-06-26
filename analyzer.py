import os
import json
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

ANALYSIS_MODEL = "openai/gpt-oss-120b"
ANALYSIS_DIR = "Call scenario analysis by bot"


def _transcript_to_text(transcript):
    lines = []
    for turn in transcript:
        speaker = turn.get("speaker", "?").upper()
        lines.append(f"{speaker}: {turn.get('text','')}")
    return "\n".join(lines)


def analyze_call(persona, transcript):
    """Have the LLM review one call transcript for agent bugs, and save a report."""
    os.makedirs(ANALYSIS_DIR, exist_ok=True)

    convo = _transcript_to_text(transcript)
    system = """You are a meticulous QA analyst reviewing a phone call between a simulated patient (the CALLER) and a medical office's AI scheduling agent (the AGENT).

Your job: judge ONLY the AGENT's behavior. Find real bugs and quality issues — things the agent got wrong, handled poorly, or missed. Ignore any imperfections from the caller; the caller is a test actor.

Be specific and evidence-based. Quote the exact agent line that demonstrates each issue. Do not invent issues; if the agent handled something well, say so. Rate each issue's severity as High, Medium, or Low.

High = safety risk, wrong medical info, or data integrity failure.
Medium = task failure, confusion, repetition, or poor handling.
Low = minor awkwardness or phrasing."""

    user = f"""SCENARIO BEING TESTED: {persona['scenario']}
WHAT THIS CALL IS DESIGNED TO PROBE: {persona.get('tests', 'general quality')}

TRANSCRIPT:
{convo}

Return ONLY JSON in this shape:
{{
  "scenario": "{persona['scenario']}",
  "primary_test_result": "<did the agent pass or fail the specific thing being probed? explain briefly>",
  "issues": [
    {{"severity": "High|Medium|Low", "issue": "<what went wrong>", "evidence": "<exact agent quote>"}}
  ],
  "did_well": ["<things the agent handled correctly>"],
  "overall": "<one-sentence summary>"
}}"""

    resp = groq_client.chat.completions.create(
        model=ANALYSIS_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=900,
        temperature=0.3,
    )
    raw = resp.choices[0].message.content.strip()

    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception:
        data = {"scenario": persona["scenario"], "raw_analysis": raw}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(ANALYSIS_DIR, f"analysis_{persona['id']:02d}_{persona['scenario']}_{ts}.md")

    with open(path, "w") as f:
        f.write(f"# Call Analysis — {persona['name']} ({persona['scenario']})\n\n")
        f.write(f"**Persona:** {persona['name']}  \n")
        f.write(f"**Scenario probed:** {persona.get('tests','')}\n\n")
        if "raw_analysis" in data:
            f.write(data["raw_analysis"])
        else:
            f.write(f"## Primary test result\n{data.get('primary_test_result','')}\n\n")
            f.write("## Issues found\n")
            issues = data.get("issues", [])
            if not issues:
                f.write("_None flagged._\n")
            for it in issues:
                f.write(f"- **[{it.get('severity','?')}]** {it.get('issue','')}\n")
                if it.get("evidence"):
                    f.write(f"  - Evidence: \"{it['evidence']}\"\n")
            f.write("\n## What the agent did well\n")
            for d in data.get("did_well", []):
                f.write(f"- {d}\n")
            f.write(f"\n## Overall\n{data.get('overall','')}\n")

    print(f"🔎 Bug analysis saved: {path}")
    return path
