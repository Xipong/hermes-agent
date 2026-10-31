---
title: "Dream Loop — Build stunning 3D scenes via a concept-art fidelity loop"
sidebar_label: "Dream Loop"
description: "Build stunning 3D scenes via a concept-art fidelity loop"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Dream Loop

Build stunning 3D scenes via a concept-art fidelity loop.

## Skill metadata

| | |
|---|---|
| Source | Optional — install with `hermes skills install official/creative/dream-loop` |
| Path | `optional-skills/creative/dream-loop` |
| Version | `1.0.0` |
| Author | Anshu Chimala (adapted by Nous Research) |
| License | MIT |
| Platforms | linux, macos |
| Tags | `3d`, `games`, `webgl`, `threejs`, `image-generation`, `visual-fidelity`, `creative` |
| Related skills | [`p5js`](../../bundled/creative/creative-p5js.md), [`claude-design`](../../bundled/creative/creative-claude-design.md), [`manim-video`](../../bundled/creative/creative-manim-video.md) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Dream Loop Skill

An autonomous process for building extremely impressive visuals, especially 3D
scenes (games, apps, usually browser three.js/WebGL): generate photorealistic
concept art of the ideal result, build it, compare a screenshot of the live
build with the concept, and refine concrete visual gaps within the task's
budget. Use the assessment ladder when scoring helps prioritize those gaps.
Goal: the most visually stunning result at an acceptable frame rate for the
target platform (e.g. 60 fps browser, 120 fps modern mobile).

This skill does NOT cover general web-app functionality, 2D UI design, or
non-visual quality — only the visual-fidelity loop.

## When to Use

- User says "dream loop" or asks for a game/scene/app built to a very high
  level of graphical fidelity.
- Follow-up refinement passes on an existing visual product (see Follow-up
  loops below).

## Prerequisites

- **Concept art**: use a supplied or established target image, or generate one
  with `image_generate`. If no target can be obtained, ask for a concept image
  rather than claiming a concept-matching result.
- **Screenshots**: `browser_exec` — serve the build locally
  (`python3 -m http.server` for static builds), then `new_tab(url)`,
  `wait_for_load()`, `capture_screenshot()`.
- **Visual comparison**: `vision_analyze` (see Assessment for the
  one-image-per-call workaround).
- **Optional**: Blender for asset modeling — see the `blender-3d-automation`
  skill. `delegate_task` for parallel asset work and fresh-context judging.

If a required capability is unavailable, state the blocked deliverable and
what can still be verified. Do not claim visual matching from source or
technical checks alone.

## Quick Reference

| Stage | What happens | Artifacts (`.dream-loop/`) |
|---|---|---|
| 1. Target | Get/confirm the user's description | notes |
| 2. Concept | Generate "in-engine screenshot" concept art | `concept.png` |
| 3. Budget | Record time budget & start time (if given) | notes |
| 4. Build | Implement the concept as well as possible in one go | source, plans |
| 5. Screenshot | Capture live build at concept resolution | `round-N.png` |
| 6. Assess | Compare live screenshot with concept; identify concrete gaps | findings |
| 7. Optional second opinion | Resolve a specific uncertainty or requested independent review | review evidence |
| 8. Refine/Exit | Address material gaps within budget, or deliver per criteria | — |

## Procedure

### 1. The target concept

If the user provided a description of a game, scene, or app, proceed — don't
ask for clarification unless it's too vague to generate concept art from. If
they didn't, ask for it.

Put working context/files in `.dream-loop/` and gitignore it (unless told
otherwise).

### 2. Concept art

The concept is a realistic, high-quality, impressive target: the look of a
current AAA game running in real time. Physically plausible materials (wet
stone, brushed metal, cloth, glass) with real roughness and normal detail,
correct proportions, atmosphere (fog, haze, rain, dust, volumetric light),
cinematic lighting with a clear key and rich shadows. It should NOT be
stylized or an artistic rendition — it should look like a true screenshot of
the ideal result.

Avoid these failure modes when generating with `image_generate`:

- **Overbaked**: photographic clutter, film grain, hundreds of unique small
  objects, excessive detail on every surface that reads as noise. A real-time
  build with modeled assets won't match this, and it won't even look good.
- **Oversimplified**: cartoon or toy look, flat shading, blobby primitive
  shapes, empty surfaces. Boring; will not impress the user.

Aim for the middle ground: beautiful surfaces and materials that shaders
render well, strong atmosphere and lighting, an interesting palette, and
focused hero elements with fine detail that draws the eye (not every element
fighting for attention).

Prompt for "in-engine screenshot" more than "concept art" and discourage the
noisy/grainy look. Review the image with `vision_analyze`; if it hits a
failure mode, pass it back to `image_generate` in edit mode and ask it to fix
the issue. Save it as `.dream-loop/concept.png`.

Check generated art against the brief before building. Ask for confirmation
when the user reserved that decision or the image introduces a material
unresolved art-direction choice; otherwise proceed with the stated direction.

### 3. Time budget

If the user gives a time or cost budget, record it and check remaining budget
between rounds. Prioritize the largest visible gaps and preserve accepted work;
stop at the limit with the best verified result and disclose unfinished parts.
Parallel work is useful for independent assets, not a requirement.

Without an explicit budget, work toward the requested fidelity and performance,
not indefinite score optimization. Another round needs a concrete unresolved
requirement and a plausible improvement; discuss a material scope or cost
expansion before undertaking it.

### 4. Build loop

Look at the concept art and implement it in one go, making that first pass
count across every tier of the score ladder: composition, textures, lighting,
details. Sculpt and model assets carefully (or use external ones if allowed);
don't settle for basic procedural elements and flat surfaces unless the art
style calls for it. Write intermediate files/plans to `.dream-loop/`.

- If Blender is installed and the concept involves 3D assets, prefer modeling
  in Blender (see the `blender-3d-automation` skill). For complex assets,
  delegate to subagents via `delegate_task`.
- If the user allows external assets, prefer them over modeling unless the
  asset is simple. If unspecified, assume NO external assets from the web.
- Do not be lazy with key environmental details (scenery, flooring,
  buildings): simple shapes look blocky, shiny, flat, and fake. Tiny details
  and texturing matter and need custom sculpting.
- Use `image_generate` for textures, normal maps, skyboxes, etc. — better
  looking and faster than procedural ones.

### 5. Screenshot

Serve the build (e.g. `python3 -m http.server` in the build dir), then via
`browser_exec`: `new_tab('http://localhost:8000')`, `wait_for_load()`, allow
the scene to settle, `capture_screenshot()`. Target the same resolution and
aspect ratio as the concept art so the comparison is fair. Save as
`.dream-loop/round-N.png`.

### 6. Compare the live result

Inspect the candidate screenshot beside the concept. Identify missing or
incorrect objects, scale, perspective, positioning, materials, lighting,
contrast, color and rendering artifacts. Prioritize the gaps visible at the
intended viewing size. Keep concise findings for the changes that matter;
a second audit log before assessment is not required.

### 7. Assessment

Self-assessment is sufficient for routine refinement. Use a fresh reviewer
when an independent review is requested or a specific uncertainty warrants
it, not automatically each round. Supply the concept and current screenshot;
add previous evidence when needed to check a claimed improvement.

Mechanics: `vision_analyze` takes one image per call. Make sequential calls
for the concept and screenshot, or stitch a labeled side-by-side composite
with ImageMagick (`convert concept.png shot.png +append compare.png`) or PIL
and analyze that single image.

Optional scored assessment:

Use this ladder when a score helps prioritize fidelity work or the user asks
for scored comparison. Scores describe visual evidence; they do not replace
performance measurements or technical acceptance. If using the ladder, retain
its gated meaning:

> Compare the screenshot to the concept and score it 0-10. A frame cannot
> score above a tier's cap until every requirement of the tiers below it is
> fully met.
>
> - **Tier 1, shape (0-3):** camera, framing, composition, and the position
>   and rough scale of every major object match the concept. Layout, not
>   finish: every major element present, in the right region of the frame
>   (within ~10% of frame width/height), at roughly the right size (within
>   ~25%). Right place and vaguely correct outline passes even if edges and
>   surface are wrong; save precision nitpicks for Tier 4. Cap 3 until true.
> - **Tier 2, light and color (3-5):** key light direction and color, overall
>   exposure (no clipping to black or white), shadow depth, palette,
>   contrast, atmosphere. Attend to reflections, glows, etc. Ensure the scene
>   is not too bright or dark relative to the concept. Judge the whole frame,
>   not tiny details (Tier 4). Cap 5 until lighting/reflections/color/
>   contrast are generally right.
> - **Tier 3, materials and surfaces (5-7):** every surface reads as the
>   right material at a glance: textures, roughness, translucency, wetness,
>   reflections. Assets must not look procedural, blocky, smooth/plastic;
>   frame-dominating elements should be properly sculpted and detailed. Cap 7
>   until true.
> - **Tier 4, fine detail (7-9):** the small things. Nitpick relentlessly;
>   inspect every little object up close. Layout aligns near-perfectly;
>   materials extremely convincing. Cap 9 until right.
> - **Tier 5, indistinguishable (9-10):** holds up side by side and zoomed
>   in. Nitpick every pixel.
>
Report the concrete visual gaps and the changes likely to address them,
ordered by impact. Identify elements and magnitudes where observable rather
than saying only "looks synthetic". For a comparison, check the earlier
findings against current evidence rather than carrying directives forward
as obligations. State uncertainty when the screenshot cannot resolve a claim.

### 8. Refine or deliver

Deliver when the requested visual fidelity is supported by the actual
screenshots, the target FPS is measured and acceptable, and relevant technical
checks pass. An optional score alone is not acceptance.

If FPS is unacceptable, optimize low-impact costs first, then inspect the
affected visual result and measure again. If visual gaps remain, address the
largest actionable causes rather than adjusting parameters without a reason.
When repeated local changes do not help, reconsider asset strategy, lighting,
composition or camera within the authorized scope; do not trigger an expensive
rebuild merely because a score stayed flat.

Stop at the user budget or a concrete blocker. Preserve improvements, explain
the remaining gap and offer options. Revert demonstrated regressions selectively
rather than using a score delta as the sole reason to keep or discard a round.

## Follow-up loops

When building on an existing product (or the user re-invokes the skill for
refinements), don't create new concept art in a vacuum — it may diverge from
what exists. Instead capture a live screenshot of the current product and
prompt `image_generate` to render the best possible version of it (current
screenshot → AAA-graphics version of the same shot), then use that as the
target. Multiple screens can be refined in parallel if asked, at higher
token cost.

## Pitfalls

- Overbaked or oversimplified concept art (see failure modes) — fix the
  concept before building against it.
- Treating a reviewer score or technical pass as proof of a good live result.
- Screenshot at a different resolution/aspect than the concept — unfair
  comparison, noisy verdicts.
- Tunnel-visioning on incremental tweaks when evidence points to a wrong
  asset, composition or lighting approach.
- Judging both images in one `vision_analyze` call — it takes one image;
  composite them first.
- Screenshotting before the scene loads/settles — add a wait after
  `wait_for_load()` for asset streaming and animation warm-up.

## Verification

- The target concept exists and is consistent with the brief; requested
  user approvals were respected.
- The delivered build has current live screenshots inspected against that
  target and an FPS measurement at the intended settings.
- Show the final screenshot and deliver the working build/source, measured
  performance, relevant technical check results and remaining limitations.
  Distinguish visual acceptance from functionality or runtime checks not run.

---
Adapted from [dream-loop](https://github.com/achimala/dream-loop) by Anshu
Chimala (MIT). Upstream license vendored as `LICENSE.txt`.
