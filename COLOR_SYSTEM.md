# Vestigo Color System

This document defines the Vestigo color system.

- The Django Tailwind and DaisyUI theme source lives in `vestigo/static/src/project.css`.
- The compiled stylesheet served by Django lives in `vestigo/static/css/project.css`.

## Prefixes By Surface

| Surface | Tailwind utilities | DaisyUI components |
|---------|--------------------|--------------------|
| Extension | `bg-primary`, `text-base-content` | `btn`, `alert`, `badge` |
| Django templates | `bg-primary`, `text-base-content` | `btn`, `alert`, `badge` |

## Semantic Colors

| Token | Tailwind utility example | Use for |
|-------|--------------------------|---------|
| `primary` | `bg-primary` | Main CTAs, links, active states |
| `secondary` | `bg-secondary` | Secondary actions |
| `accent` | `bg-accent` | Highlights, emphasis |
| `neutral` | `bg-neutral` | Dark surfaces, sidebars |
| `info` | `bg-info` | Informational messaging |
| `success` | `bg-success` | Positive states |
| `warning` | `bg-warning` | Caution states |
| `error` | `bg-error` | Errors, destructive states |

## Base Colors

| Token | Tailwind utility example | Use for |
|-------|--------------------------|---------|
| `base-100` | `bg-base-100` | Main background |
| `base-200` | `bg-base-200` | Secondary background |
| `base-300` | `bg-base-300` | Borders, tertiary surfaces |
| `base-content` | `text-base-content` | Primary text |

## Django Examples

```html
<section class="bg-base-100 text-base-content">
  <div class="card border border-base-300">
    <div class="card-body">
      <h2 class="card-title">Warmup status</h2>
      <p class="text-base-content/70">Mailbox health is improving.</p>
      <div class="flex gap-3">
        <button class="btn btn-primary">Continue</button>
        <button class="btn btn-ghost">Later</button>
      </div>
    </div>
  </div>
</section>
```

## Color Values Reference

| Name | OKLCH value | Approximate hex |
|------|-------------|-----------------|
| `base-100` | `oklch(100% 0 0)` | `#FFFFFF` |
| `base-200` | `oklch(97% 0.005 260)` | `#F9FAFB` |
| `base-300` | `oklch(93% 0.01 260)` | `#F3F4F6` |
| `base-content` | `oklch(25% 0.02 260)` | `#1F2937` |
| `primary` | `oklch(55% 0.22 250)` | `#3B82F6` |
| `secondary` | `oklch(55% 0.02 260)` | `#6B7280` |
| `accent` | `oklch(68% 0.16 55)` | `#C87830` |
| `neutral` | `oklch(35% 0.02 260)` | `#374151` |
| `info` | `oklch(62% 0.06 250)` | `#6B8DB5` |
| `success` | `oklch(70% 0.18 145)` | `#22C55E` |
| `warning` | `oklch(82% 0.18 85)` | `#EAB308` |
| `error` | `oklch(60% 0.22 25)` | `#EF4444` |
