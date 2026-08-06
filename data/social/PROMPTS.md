# Image & video prompt pack

Generate these manually in the Gemini app, then drop the files where noted. The
pipeline picks them up from there — see "Where to save" at the bottom.

Everything shares one **style block** so the whole site looks like one publication
rather than a pile of stock art. Paste the style block into every prompt.

---

## The style block

Copy this verbatim into every image prompt:

> Deep warm charcoal background (#121110) with subtle paper grain. Thin muted teal
> (#6fd3bf) linework as the primary element, sparse off-white (#f2efe9) accents.
> Minimal and restrained, generous negative space, high-end print magazine
> aesthetic. Convey the idea through geometry alone. Absolutely no text, no
> letters, no numbers, no UI elements, no code, no logos.

**Why no text:** image models render text badly, and your layout already puts real
type over the image. Any generated lettering will fight it and look broken.

**Aspect ratio:** `16:9` for blog covers. `9:16` for anything vertical.

---

## Blog covers (16:9)

### what-broke-running-agents ✅ done
Already generated and saved. Use it as the reference for tone.

### top-programming-languages-to-know-early-in-2026
> Several parallel vertical columns of varying height, like a bar chart abstracted
> into pure line, some rising and some receding, suggesting shifting ranks over
> time. One column subtly taller and brighter than the rest.
> *(+ style block, 16:9)*

### mistakes-to-avoid-when-building-ai-agents-and-how-to-recover
> A single continuous line that repeatedly veers off course and corrects itself,
> tracing a path across the frame — each deviation marked by a small geometric
> node, the line ending steady and straight.
> *(+ style block, 16:9)*

### latest-trends-in-ai-a-guide-to-2026
> Concentric arcs radiating outward from a dense cluster at the lower left,
> spreading and thinning toward the upper right, suggesting expansion and
> diffusion over time.
> *(+ style block, 16:9)*

### recent-trends-in-ai-a-comprehensive-guide
> An orderly grid of small geometric marks that gradually loosens and reorganises
> toward the right edge into a looser, more organic arrangement.
> *(+ style block, 16:9)*

### 3-practical-ways-students-in-nepal-can-use-ai-tools-for-stud
> Three distinct paths starting at separate points on the left and converging on
> a single bright node at the right. Clean, hopeful, uncluttered.
> *(+ style block, 16:9)*

### how-students-in-nepal-can-leverage-ai-tools-for-academic-suc
> A stepped ascending structure drawn in thin line, like a staircase abstracted
> to its edges, rising left to right with soft light gathering at the top step.
> *(+ style block, 16:9)*

### hello-world
> A single point at the left expanding into a widening cone of fine lines toward
> the right edge. Quiet, spacious, a beginning.
> *(+ style block, 16:9)*

---

## Video loops (9:16, ~8 seconds, silent)

These sit behind your slide text or as a post header. `PostMedia.astro` already
prefers `video` over `cover`, so a loop replaces the cover automatically.

**Rules that matter for this use:** no camera shake, no fast cuts, no subject
matter that demands attention. It is a background — if it competes with the text
it has failed. Ask for a **seamless loop** so the join is invisible.

### ambient-lines
> Extremely slow horizontal drift of thin muted teal lines across a deep warm
> charcoal field with paper grain. Barely-there motion, hypnotic and calm.
> Seamless loop, no camera movement, no subjects, no text. Vertical 9:16.

### ambient-nodes
> Sparse geometric nodes on a deep warm charcoal field, connected by thin teal
> lines that slowly pulse brighter and dimmer in sequence. Very slow, minimal.
> Seamless loop, static camera, no text. Vertical 9:16.

### ambient-drift
> Fine off-white particles drifting slowly upward through a deep warm charcoal
> void, with faint teal linework far in the background. Meditative, extremely
> slow. Seamless loop, static camera, no text. Vertical 9:16.

---

## Where to save

**Blog covers** → `blog-site/public/covers/<slug>.png`

The slug must match the post filename exactly. For example:
`blog-site/public/covers/top-programming-languages-to-know-early-in-2026.png`

**Video loops** → `blog-site/public/video/<name>.mp4`

Keep them under ~3 MB. Vercel serves them, and a heavy header video will hurt
your page-load scores more than the visual is worth.

Once files are in place, tell me and I will wire them into the posts' frontmatter
and push. Nothing needs renaming as long as the slug matches.

---

## Reusing this for future posts

For any new post, take the post's central claim and describe it as **motion or
geometry**, never as objects:

- "rate limits" → lines that stop at a boundary
- "fallback" → a path that reroutes when one branch ends
- "growth" → a form that expands rightward
- "trade-off" → two masses balancing

Then append the style block. That constraint is what keeps the set coherent — the
subject changes, the visual language never does.
