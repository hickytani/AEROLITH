# Sprint 4: Studio Geometry Recovery and Readability

**Review date:** 2026-10-20
**Starting commit:** `6a8d01d` (`Build learning and platform experiences`)
**Starting branch:** `codex/sprint-2-engineering-validation`

## Findings and limits of reproduction

The screenshot described in the Sprint 4 brief was not present as a file in the workspace, and no browser/network capture was supplied. The available CUA inventory returned `{ "apps": [], "browsers": [] }`. Therefore the specific failed browser request from that screenshot could not be observed.

The API behavior was reproduced against isolated temporary project and artifact directories. For committed revision 1, both `/api/v1/geometry/pinion.stl?revision=1` and `/api/v1/geometry/gear.stl?revision=1` returned HTTP 200 and `model/stl`. Three.js `STLLoader.parse()` successfully read both binary responses: pinion 1,872 vertices with bounds approximately `[-19.924,-19.924,-6]` to `[19.924,19.924,6]` mm; driven gear 3,600 vertices with bounds approximately `[16.024,-55.976,-6]` to `[127.976,55.976,6]` mm. This established that the default CAD generation and payloads worked in the reproduced baseline; it did not establish what happened in the unavailable screenshot session.

The confirmed diagnostic defect was in the frontend failure path: `STLLoader.load()` passed errors to a callback that discarded HTTP status and response body, then collapsed failures to “Some component geometry could not be loaded.” The component endpoint identified the design revision but did not identify the component, geometry units, or format in response headers. The UI could not distinguish an API 409 during a design change from a server error, invalid response, or malformed STL, and did not refresh after learning that the canonical revision had advanced.

During Sprint 4 integration, the new loader module initially returned 404 through Next.js: the legacy app assets are served by FastAPI, while Next.js only proxied the previously registered app and stylesheet paths. The live route check exposed this new defect. Explicit rewrites for `mesh-loader.js` and `camera-fit.js` fixed it; all four application pages and all four static assets returned HTTP 200 afterward.

## Geometry changes

- Component STL responses now include artifact ID, SHA-256, component ID, geometry revision, format (`stl`), units (`mm`), and the existing design revision and generator metadata. Responses use `Cache-Control: no-store`.
- The API checks the canonical revision again after tessellation and returns HTTP 409 with the newer revision rather than publishing a mesh generated from a superseded project.
- The browser fetches binary data explicitly, checks HTTP status and every geometry identity field, verifies SHA-256, parses STL before scene insertion, and validates finite vertices/normals, index ranges when present, nonzero bounds, and triangle structure.
- Each component loads independently. A valid mesh remains renderable when its partner fails; the UI names the failed component and exposes an actionable response error. A stale-revision response triggers a canonical project refresh and rebuild.
- The assembly still uses the existing CadQuery polygonal gear approximation. The physical model, calculation assumptions, and manufacturing limitations have not changed.
- FIT now frames the union of actual visible mesh bounds. ISO, TOP, and FRONT camera poses are calculated by a testable helper; TOP uses a non-collinear up vector. The viewer uses one scene unit per millimetre, disposes replaced mesh geometry/material, and cleans up controls, observer, helpers, renderer, and pending mesh results on teardown.
- Component selection and visibility are separate keyboard-operable controls. Component rows show tooth count and pitch diameter from the committed design.

## Readability changes

The Studio and Learn/Platform surfaces now use shared CSS font, ink, muted-text, and spacing tokens with a local system UI/monospace stack; the Google Fonts network import was removed. Body text is 16 px, form labels 14 px, supporting text and technical metadata are at least 12 px, and result values remain prominent. Contrast, focus states, button states, status text, warning treatment, panel spacing, and 760/440 px responsive breakpoints were updated. The code example and geometry-error panels wrap or scroll within their own area.

Typography declarations are contract-tested to remain at least 12 px. Because no browser was available, actual 1440×900 and 1280×720 layout, text rendering, WebGL appearance, clipping, and horizontal scrolling were not visually inspected.

## Verification

Initial Sprint 4 baseline, before edits: `npm test` passed 51 Python tests and 4 Node tests, with the existing Starlette/httpx deprecation warning. Direct API and Three.js parsing checks confirmed both baseline component meshes.

After implementation, verification included:

- `npm test`: **53 Python tests passed** and **9 Node tests passed**, with one existing Starlette/httpx deprecation warning.
- `npm run build:web`: passed compilation, TypeScript, and static generation for `/`, `/designs/new`, `/learn`, and `/platform`.
- `npx tsc --noEmit --pretty false -p apps/web/tsconfig.json`: passed.
- `node --check public/app.js`, `node --check public/mesh-loader.js`, and `node --check public/camera-fit.js`: passed.
- Live local smoke check using temporary storage: all four pages, `/app.js`, `/mesh-loader.js`, `/camera-fit.js`, and `/style.css` returned HTTP 200. Both API meshes returned the declared component/revision/units/format metadata; their SHA-256 headers matched their bytes and Three.js parsed both.
- API tests cover both gear response contracts, revision changes during generation (HTTP 409), and isolated failure for one component. Node tests cover valid/malformed/checksum-mismatched STL, stale/mismatched response identity, independent component failure, camera fit bounds/presets, and typography rules.

The first live check failed on `/mesh-loader.js` with HTTP 404 before the Next rewrite was added. It passed after the rewrite. The original screenshot’s exact failing request remains unknown.

## Capability status

**Verified by automated or live checks:** current-revision API mesh generation for both gears, binary STL structure, Three.js parsing, response identity and checksum validation, stale-revision rejection during tessellation, independent component error handling, camera-fit calculations, font-size rules, Next.js static-asset proxy routes, API tests, and production build.

**Partially verified:** interactive selection, visibility, orbit/pan/zoom, and viewport response to edits; their implementation paths are present, but no browser interaction or WebGL rendering was exercised.

**Unverified:** the exact failure in the referenced screenshot; visual review at the requested laptop sizes; actual browser focus/keyboard behavior, camera controls, persisted-value refresh, WebGL/GPU rendering, and browser network-console cleanliness.

**Unsupported:** involute or manufacturing-ready teeth, animated physical meshing, strength/contact/fatigue/thermal analysis, safety or manufacturing approval, additional engineering families, and a connected AI model.

## P0 Studio visibility incident follow-up

**Status:** the local Studio visibility incident is fixed and verified in headless Google Chrome. The exact screenshot originally referenced in the Sprint 4 brief was not supplied, but the failure was reproduced independently in the actual browser.

### Confirmed causes

1. `fill()` in `public/app.js` required `#gear-label`, which did not exist in `public/index.html`. Chrome reproduced `Could not load design: Studio interface is missing required element #gear-label.` The `load()` catch displayed this and exited before `build()` requested either STL. The fix adds the expected output-ratio label to the assembly stage bar. A frontend contract test now checks that every statically required app element exists in the HTML.
2. In the Next.js development build, React Strict Mode ran the `WorkspaceShell` effect setup/cleanup/setup sequence. Each effect inserted a versioned module script. Cleanup used a broadcast disposal event, so a late cleanup from a removed script could dispose the active module's renderer. The duplicate module listeners could also apply one click more than once. Disposal now carries the script instance ID; each module ignores other instances, and disposed modules' UI handlers no-op. The browser acceptance applied the change once and observed exactly one revision advance.
3. After the JavaScript initialization blockers were removed, a 1440×900 browser capture still showed an empty viewport: the results rail stretched the stage viewport to approximately 1,395 px high, placing the fitted gears below the visible screen. Desktop stage height is now capped relative to `100vh`, so FIT uses the actual screen-sized canvas. At 1440×900 the canvas measured 650×502 px; at 1280×720 it measured 572×382 px and ended above the viewport bottom.

The combined launcher also started Next.js before the API was ready. This was reproduced as an initial project request and static/API proxy requests returning 500 with `ECONNREFUSED`; the Studio's initial request did not retry. `scripts/run.mjs` now waits for a successful `/api/v1/health` response before launching Next.js, with a bounded timeout and a clear startup error.

### Files changed for the incident

- `public/index.html` — supplies the required output-ratio element.
- `public/app.js` and `apps/web/app/WorkspaceShell.tsx` — scope cleanup to the script instance and guard disposed instance interactions.
- `public/style.css` — constrain the desktop viewport to the available screen height.
- `scripts/api-readiness.mjs` and `scripts/run.mjs` — wait for API health before starting Next.js.
- `tests/frontend-contract.test.mjs` — cover required HTML elements, instance-scoped cleanup, bounded viewport sizing, and API startup readiness.
- `scripts/browser-acceptance-p0.mjs` — repeatable Chrome DevTools Protocol acceptance runner; it writes local screenshots to ignored `artifacts/`.

### Actual Chrome acceptance

Chrome was launched headlessly at a 1440×900 device viewport with WebGL enabled. The runner observed a nonzero canvas and a working WebGL context; no geometry error was shown. Both STL requests returned HTTP 200 with `model/stl`, matching component IDs, matching revision headers, millimetre units, artifact IDs and SHA-256 values. The UI reported **2 component meshes** for the active revision. The rendered pinion and driven gear were visually confirmed in the captured browser image.

The runner exercised ISO, TOP, FRONT and FIT; screenshots had distinct rendered output for the three camera directions. Pointer drag, right-button pan and wheel zoom each changed rendered pixels. Hiding the pinion changed the rendered image and toggled its visibility control; selecting the driven gear changed its selection state and rendered color. Returning to the demo then applying 12/30 teeth and module 2 mm advanced exactly one revision. The resulting state was ratio 2.5:1, center distance 42 mm, ideal output speed 360 rpm and ideal output torque 20 N·m. After a full page refresh, inputs, results and geometry still reported the same committed revision.

Screenshots captured from Chrome:

- 1440×900 after applying the 12/30 design: `artifacts/p0-studio-accepted.png`
- 1280×720: `artifacts/p0-studio-1280x720.png`

The browser console/network trace showed successful Studio module, stylesheet, Three.js vendor and geometry requests. The only final HTTP error responses were Chrome's automatic `/favicon.ico` requests (404); no geometry or application API request failed during acceptance. The backend model remains an educational polygonal approximation with the engineering limits stated above.

### Verification after the incident fix

- Focused frontend tests: **12 passed**.
- Chrome acceptance runner: passed at both viewport sizes; 12/30 interaction and persisted revision **3** verified in the final clean-browser run, with both components loaded.
- Final `npm test`: **53 Python tests and 12 Node tests passed**, with the existing Starlette/httpx deprecation warning.
- `npm run build:web`, standalone TypeScript check and JavaScript syntax checks passed.
- At the time this report was written, the P0 implementation and report changes were still uncommitted; the pre-existing `apps/web/next-env.d.ts` edit was preserved.

The earlier Sprint 4 browser-unavailable statements above describe the original review. This incident follow-up supersedes its visual-rendering status with actual Chrome evidence; the original unsupplied screenshot's exact session remains unavailable.
