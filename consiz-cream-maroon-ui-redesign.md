# Consiz UI Redesign — Cream & Maroon Theme

## Goal

Restyle the existing Consiz Windows desktop UI from the current dark blue/black treatment to a warm, editorial **cream and maroon** visual system. Preserve all existing functionality, screen hierarchy, copy, steps, and interactions; this is a visual redesign, not a product-flow rewrite.

The result should feel calm, premium, intelligent, and distinctly desktop-native — like a beautifully considered productivity companion, not a web dashboard or a generic AI interface.

## Reference screens to update

- Onboarding / setup wizard (Steps 1–4), including welcome, user details, and final setup states.
- The floating answer panel that appears beside the cursor.
- Any shared controls: buttons, inputs, dropdowns, cards, scrollbars, menus, toasts, and empty/loading states.

## Theme direction

Use warm paper-like surfaces with dark wine accents. Avoid pure white, pure black, neon, gradients, glassmorphism, blue accents, and oversized rounded “SaaS” components.

### Core tokens

```css
--cream-50:  #FFFCF6; /* lightest canvas */
--cream-100: #F8F1E3; /* main app background */
--cream-200: #EFE3D0; /* elevated surface / selected neutral */
--cream-300: #DDCBB0; /* border */

--maroon-900: #43151B; /* main text / deepest contrast */
--maroon-800: #611E29; /* headers */
--maroon-700: #7A2835; /* primary interactive */
--maroon-600: #943846; /* hover / active */

--ink-muted:   #765A56; /* secondary copy */
--success:      #4E6A45; /* restrained confirmation state */
--warning:      #A55D24; /* restrained warning state */
--focus-ring:   #A84D59; /* visible accessibility focus */
```

## Layout and surfaces

- Use `--cream-100` for the main window background and `--cream-50` for inputs or inset panels.
- Make the content feel spacious: generous padding, simple alignment, and clear visual rhythm.
- Use a 1px warm beige border (`--cream-300`) rather than shadows as the default separation.
- Use shadows sparingly and softly only for floating UI: `0 12px 32px rgba(67, 21, 27, 0.14)`.
- Window chrome should be cream, with a subtle bottom divider. Keep the OS controls visible and native-looking.
- Retain compact desktop proportions. Do not turn the wizard into a full-page web landing screen.

## Typography

- Prefer **Inter**, **Manrope**, or the closest existing clean system sans-serif.
- Headings: 700 weight, maroon-900, tight but readable tracking.
- Body: 400–500 weight, maroon-900. Increase line-height for the explanatory onboarding text.
- Supporting labels, step indicators, helper text: ink-muted.
- Do not use all-caps for paragraph text. Small all-caps is acceptable only for tiny metadata such as `STEP 1 OF 4`.

## Wizard redesign details

### Header and progress

- Replace the current plain “Step X of 4” treatment with a small maroon label and a thin progress indicator.
- Place the step text above a 4-segment progress rail. Completed segments: maroon-700; current segment: maroon-600; future segments: cream-300.
- Keep this understated; it should guide rather than dominate.

### Welcome screen

- Keep the Consiz feather mark small and refined in the title bar.
- Use a large maroon heading: “Welcome to Consiz”.
- Present the description as short, readable paragraphs in dark maroon rather than stark white text.
- Add a subtle abstract feather/selection motif in a very pale maroon outline or cream-200 panel; it must stay decorative and never compete with the text.
- Place actions in a stable footer area separated by a hairline border.

### Form screen

- Labels should be clear, maroon-800, 14–15px, medium weight.
- Inputs and select fields: cream-50 fill, cream-300 border, 8px corner radius, 44px minimum height.
- On hover, gently darken the border. On focus, use maroon-700 border plus a 3px low-opacity focus ring.
- Replace native-looking white dropdown bars with styled cream fields that have a small maroon chevron.
- Keep the name field filled with the user’s existing data; do not alter onboarding content or options.

### Buttons

- Primary actions (`Get Started`, `Continue`, `Finish`): maroon-700 background, cream-50 text, 8px radius, medium-to-semibold weight.
- Primary hover: maroon-600. Pressed: maroon-900. Disabled: cream-300 background with muted text.
- Secondary actions (`Back`, `Cancel`): transparent or cream-50 fill, maroon-800 text, cream-300 border.
- Buttons must remain high contrast and keyboard-focusable.

## Floating answer panel

- Transform the existing dark answer popup into a compact warm-paper panel: cream-50 surface, 1px cream-300 outline, soft maroon-tinted shadow.
- Use a thin maroon top accent or a small feather icon for identity; avoid a thick banner.
- Main answer text: maroon-900. Status or source details: ink-muted.
- Retain utility controls such as **Ask** and **Copy**, but style them as compact actions:
  - `Ask`: filled maroon button.
  - `Copy`: outlined cream/maroon button.
- Error states must not use the old dark theme. Use a pale warm surface with a small warning icon and clear maroon copy. Keep technical error details visually secondary.
- Preserve existing functionality and message wording unless an existing line is clearly a placeholder.

## Interaction and accessibility

- Maintain WCAG-friendly contrast for all readable text and controls.
- Provide visible keyboard focus everywhere.
- Keep transitions fast and restrained: 140–180ms ease-out for hover/focus; no bouncy or dramatic motion.
- Respect the system reduced-motion preference.
- Do not rely on colour alone for errors, completion, selected state, or focus.

## Implementation rules

1. Reuse the existing component structure and state logic.
2. Centralize the above colours as theme tokens / CSS variables so later adjustments are easy.
3. Replace all legacy dark background, blue primary, and stark white control values throughout the app.
4. Keep the visual language consistent across every onboarding step and overlay.
5. Test at the app’s current desktop window size so no footer actions are clipped.
6. Do not add new product features, screens, onboarding questions, logos, or marketing claims.

## Acceptance checklist

- Every visible screen uses cream backgrounds and maroon as the primary accent.
- No old blue primary button, black app panel, or harsh white dropdown remains.
- Forms look intentionally designed rather than like default OS widgets.
- The wizard remains easy to scan and navigate with mouse or keyboard.
- The answer popup is readable, polished, and visually related to the onboarding experience.
