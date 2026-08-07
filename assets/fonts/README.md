# Bundled fonts

These are committed deliberately so a Linux server renders slides identically to
a Windows laptop. Without them the Linux fallback is DejaVu, and the same deck
comes out looking like a different publication.

| File | Family | Used for | Licence |
|---|---|---|---|
| `Fraunces.ttf` | [Fraunces](https://fonts.google.com/specimen/Fraunces) | headings, hooks | SIL Open Font License 1.1 |
| `Inter.ttf` | [Inter](https://fonts.google.com/specimen/Inter) | body, labels | SIL Open Font License 1.1 |

Both are the same typefaces the blog uses, so slides and site match.

**The OFL permits redistribution, which is why these can live in the repo.**
Do not add Georgia, Calibri, Consolas or any other Microsoft or Apple system
font here — those are licensed to the machine, not to you, and committing them
to a public repository is a licence violation. The renderer already falls back
to them locally when present, which is all that is needed.

Both files are variable fonts. `render_slides.FONT_WEIGHTS` sets the weight axis
per role; without that, Inter renders every weight at 400 and headings come out
looking like body copy.
