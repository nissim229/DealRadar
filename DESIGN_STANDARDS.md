# DealRadar Design Standards

The rules below are what's already established in the codebase — written down
so new pages/features (like Cars) can be checked against them instead of
drifting. Where existing code violates a rule, that's noted as a known gap,
not a new convention to follow.

Core infrastructure: `design_tokens.py` (CSS custom properties), `theme.py`
(light/dark theming for native widgets), `icons.py` (SVG icon set for raw
HTML), `nav.py` (shared left-nav component).

## 1. Navigation

**Rule**: any "pick a section, see different content" control uses
`nav.py`'s `render_side_nav()`. Nothing else — not `st.tabs()`, not a
horizontal `st.radio()` — represents section navigation.

**Known gaps (not yet migrated):**
- `components/property_card.py:181` — property detail dialog (Why This
  Grade / What-If / Photos / Notes) still uses `st.tabs()`.
- `components/portfolio.py:994` — top-level Portfolio page switch (My
  Properties / Add a Property / Summary) still uses `st.tabs()`.
- `components/analytics.py`'s per-property "Full Underwriting Breakdown"
  sub-tabs — deliberately left as `st.tabs()` (out of scope in the last
  standardization pass, revisit later).
- `theme.py`'s `theme_toggle_control()` (Light/Dark/Auto, used in Settings)
  — horizontal `st.radio()`.
- `components/portfolio.py:170-173, 274-277, 866-869` — three more
  horizontal radios (loan-calculator mode, payment-schedule view, portfolio
  chart-type picker).
- `components/admin_controls.py:373-374` — promo discount type radio.
- `components/analytics.py:526-529` — scan-results view mode (Properties/
  Map/Table) — **exception, keep as-is**: this is a display-mode switch on
  one dataset, not section navigation (explicit user decision).
- `components/auth_portal.py:213-214` — Sign In / Register toggle —
  reasonable candidate to leave as a radio (it's a 2-state mode switch on a
  standalone auth screen, not in-app section nav) but worth a deliberate
  call, not an oversight.

## 2. Tables

- Every `st.dataframe(...)` sets `height=len(df) * 35 + 38` (or
  `min(len(df), N) * 35 + 38` for a capped preview) — never the ~10-row
  Streamlit default.
- Always `hide_index=True`.
- Use `width="stretch"`, not the deprecated `use_container_width=True`.
  **Known gap**: every `st.dataframe`/`st.button`/`st.link_button`/
  `st.form_submit_button`/`st.popover` call in the app currently uses
  `use_container_width=True` — internally consistent, but all on the
  deprecated API. Worth one repo-wide find/replace pass rather than
  per-file fixes.

## 3. Pagination

The established shape (5 instances, all identical):
```python
col1, col2, col3 = st.columns([1, 2, 1])
with col1:
    st.button(":material/chevron_left: Previous", disabled=current_page <= 1, ...)
with col2:
    st.markdown(f"Page {page} of {total} · {count} total X")  # centered, muted caption style
with col3:
    st.button("Next :material/chevron_right:", disabled=current_page >= total, ...)
```
Match this exactly for any new paginated table.

## 4. Hero banners

Every page header uses the same shell: `var(--radar-gradient-hero)`
background, a centered 48×48px `var(--radar-gradient-brand)` icon box
(via `icons.py`'s `icon()`), a 32px/800-weight white title, and a 16px
`var(--radar-text-on-dark-muted)` subtitle underneath. See
`components/strategy_config.py`, `components/portfolio.py`, or
`components/admin_controls.py` for the reference markup.

## 5. Stat cards

Two intentionally different conventions coexist — pick the right one:
- **`render_stat_card()`** (`components/analytics.py`) — a static div
  (icon + value + label, colored left border) for a plain read-only stat.
  Import and reuse this; don't write a new inline version.
- **CSS-restyled `st.button`** (`nav.py`'s active-item style,
  `_render_clickable_hero_card()` in analytics.py, admin's stat cards) —
  used only when the "stat card" needs to be clickable (opens a dialog).

**Rule**: accent/border colors always come from `design_tokens.py`
(`var(--radar-success)`, `var(--radar-primary)`, etc.), never a hardcoded
hex — even a hex value that happens to match a token's underlying color
still isn't tokenized, so a future rebrand would miss it silently.
**Known gaps**: `components/portfolio.py` and the dashboard hero cards in
`components/analytics.py` hardcode `#7c3aed` and `#059669` (which isn't
even the app's real `--radar-success` green).

## 6. Buttons

- `type="primary"` for the active/affirmative action, `type="secondary"`
  otherwise — used consistently app-wide, keep doing this.
- The "real button dressed as a card" pattern (used by `nav.py`, dashboard
  hero cards, admin stat cards) is the only accepted way to make a
  clickable card — never a `<div onclick>` (Streamlit can't wire that to
  Python anyway).
- `width="stretch"`, not `use_container_width=True` (see #2).

## 7. Badges / status colors

Every colored status indicator (deal grade, suspended flag, plan badge,
promo type) must reference the `--radar-success`/`--radar-warning`/
`--radar-danger` token trio (with their `-bg`/`-border` variants) — never
a one-off hex, and never Streamlit's native `:red[...]`/`:green[...]`
markdown color shortcodes (that's a fixed palette outside the app's own
token system).

**Known gap**: `underwriting.py`'s `GRADE_STYLES` (the single source every
deal badge — property AND car — renders from) hardcodes its own hex per
grade instead of referencing the tokens, even though the values were
clearly copied from `design_tokens.py` originally. Fix this once, centrally,
and every badge in the app inherits it.
**Known gap**: `components/admin_controls.py`'s suspended-user indicator
uses `:red[SUSPENDED]` instead of a custom span like everywhere else.

## 8. Icons

- Inside a real Streamlit widget label (`st.button`, `st.tabs`,
  `st.expander`, `st.popover`, `st.form_submit_button`, `icon=` kwargs,
  or plain `st.markdown()` without `unsafe_allow_html`): use the
  `:material/name:` shortcode.
- Inside raw HTML passed to `st.markdown(..., unsafe_allow_html=True)`:
  use `icons.py`'s `icon(name, size, color)` — a `:material/` shortcode
  does **not** render there, it shows as literal text.
- **No raw emoji in UI-facing strings.** `icons.py` exists specifically so
  nothing needs to fall back to an emoji.
  **Known gap (extensive)**: deal-grade badge labels, the grade-explanation
  table, favorite-star toggles, loading-spinner icon, and several more all
  still use raw emoji — see the audit list. Not urgent to fix everything
  at once, but new code should never add another one, and grade badges
  (the most-seen instance) are the highest-value fix.

## 9. Empty states

Use `components/analytics.py`'s `render_empty_state(icon_name, title,
description, cta_label=None, cta_page=None)` for every "nothing here yet"
message — not a bare `st.info()`/`st.caption()` one-liner.
**Known gap**: `components/strategy_config.py` has its own private
near-duplicate (`_render_empty_state`, missing the CTA-button support) —
should import and use the shared one instead. Several other pages
(admin_controls, portfolio, analytics) also still use bare one-liners in
lower-traffic spots.

## 10. Color & spacing

Always reach for a `design_tokens.py` variable
(`var(--radar-space-4)`, `var(--radar-radius-md)`, `var(--radar-shadow-sm)`,
etc.) before writing a raw px/hex value in new HTML. If a value doesn't
have a token yet, that's a signal to add one, not to hardcode it locally.

## 11. Typography

Three faces, loaded once via `design_tokens.py`'s `inject_design_tokens()`
(Google Fonts, applied app-wide before the guest/auth/authenticated router
split so every page gets them):

- **`var(--radar-font-display)`** (Sora) — real headings (`h1`-`h6`,
  including every `st.markdown("##### ...")` section header) and hero
  titles/wordmarks. Used sparingly and only at larger sizes, so it stays a
  display face rather than blending into body copy.
- **`var(--radar-font-body)`** (Work Sans) — everything else: labels,
  buttons, tables, captions, form fields. Applied globally as the default,
  so new code doesn't need to set this explicitly.
- **`var(--radar-font-mono)`** (JetBrains Mono) — anywhere digits or
  identifiers need to line up: code, file paths, addresses in a data
  table.

**Rule**: a hand-coded hero title (raw `<div style="font-size:32px;...">`
rather than a real `<h1>`) needs `font-family: var(--radar-font-display)`
set explicitly in its inline style, since it isn't a semantic heading tag
the global `h1`-`h6` rule would otherwise catch automatically.

## Applying this to a new category (e.g. Cars)

A new deal category should reuse, not reinvent: `render_side_nav` for any
section switching, `render_stat_card`/the dashboard hero-card pattern for
metrics, `GRADE_STYLES`/`render_deal_badge` for its deal-quality badge,
`icons.py` for iconography, `render_empty_state` for no-results messaging,
and every color/spacing value from `design_tokens.py`. `car_card.py` is
close but has two small drifts (hardcoded gradient/color that duplicate
token values instead of referencing them) — see the audit.
