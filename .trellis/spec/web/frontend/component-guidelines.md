# Component Guidelines

> How components are built in this project.

---

## Overview

<!--
Document your project's component conventions here.

Questions to answer:
- What component patterns do you use?
- How are props defined?
- How do you handle composition?
- What accessibility standards apply?
-->

(To be filled by the team)

---

## Component Structure

<!-- Standard structure of a component file -->

(To be filled by the team)

---

## Props Conventions

<!-- How props should be defined and typed -->

(To be filled by the team)

---

## Styling Patterns

<!-- How styles are applied (CSS modules, styled-components, Tailwind, etc.) -->

(To be filled by the team)

---

## Accessibility

<!-- A11y requirements and patterns -->

(To be filled by the team)

---

## Common Mistakes

<!-- Component-related mistakes your team has made -->

(To be filled by the team)

---

## Navigation Grouping (AppShell)

`web/src/components/app-shell.tsx` holds the single `navigation: NavEntry[]` list that drives both layouts: a vertical sidebar on desktop (`lg:`) and a horizontal scrollable tab strip on mobile.

- Entries are either leaves (`{ to, label, icon }`) or groups (`{ label, icon, children }`). Groups render via `NavGroup`.
- Group toggle button is desktop-only (`hidden lg:flex`); on mobile the group's children stay flat in the tab strip — the strip has no room for hierarchy, do not try to nest it there.
- Collapse is class-based: the child `<ul>` only gets `lg:hidden`, so mobile visibility never changes. Tests assert classes + `aria-expanded`, not computed styles (jsdom applies no CSS).
- The scroll-into-view effect must target `a.nav-link.active` (links only) — group buttons also carry `.nav-link.active` and would shadow the real target.
- Auto-expand a group when `location.pathname` enters one of its children, otherwise the active item can be collapsed away.
