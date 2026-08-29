---
name: journal
description: Guide a daily reflection session and save the entry to a markdown file.
---

# Journal

Guide a reflective journaling session and save the output to a dated markdown file in a `journal/` directory.

## Steps

1. **Prompt**: Ask the user 2-3 focused questions about their day, mindset, or current focus (e.g., wins, blockers, gratitude) if they haven't provided any thoughts yet.
2. **Draft**: Synthesize their responses into a clean, well-structured journal entry with a clear date and headings.
3. **Save**: Use `run_powershell` to write the entry to `journal/YYYY-MM-DD.md` (creating the `journal/` directory if it does not exist).
4. **Confirm**: Display the saved file path and a brief excerpt to the user.

## Rules

- **Do not invent feelings or events.** Only use the reflections, thoughts, or text provided by the user.
- **Keep formatting clean and consistent.** Use standard markdown (Date header, Key Insights, Reflections, Action Items).
- **Handle missing input gracefully.** If the user invokes `/skill journal` with raw thoughts or text already in the prompt, skip the prompting step and directly format and save it.
- **Do not preach or give unsolicited advice.** Maintain a supportive, neutral, and reflective tone.

## Output

Emit a short confirmation showing the saved file path and the generated journal title.
