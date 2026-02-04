---
name: ""
overview: ""
todos: []
isProject: false
---

# Pager: prevent movement until threshold, with click/scroll propagation

## Required behavior

1. **Page must not move during the gesture** when the swipe shouldn’t count (no partial drag).
2. **Clicks must propagate** to the content.
3. **Nested scrollable content** must work.
4. **Full overlay is not acceptable** (blocks clicks and scroll).
5. **Edge strips are not acceptable** either.

## Only remaining option: parent observes in Initial pass (no overlay)

Use **PointerEventPass.Initial** so the **parent** receives pointer events **before** the child, without being the hit-test target:

- Put the swipe observer on the **parent Box** that already wraps the pager (the same `Box(modifier = ...) { Pager { content } }`).
- In that modifier use `pointerInput` and inside `awaitPointerEventScope` call `**awaitPointerEvent(PointerEventPass.Initial)**` (or the equivalent API in your Compose version) so events are received in the Initial pass (parent to child).
- **Do not consume** any events. Only read position/delta to track `totalDrag`.
- Events then continue to the **child** (pager / scrollable content), so the hit target still gets them — clicks and nested scroll work.
- Pager keeps `**userScrollEnabled = false**` when we handle swipe, so the page does not follow the finger.
- On pointer release, if `|totalDrag| >= thresholdPx` call `animateScrollToPage(prev/next)`; otherwise do nothing.

So: no overlay, no edge strips; the existing parent Box observes in Initial pass, does not consume, and triggers page change only when the swipe is over threshold.

## Implementation steps

1. **Confirm API:** In the Compose (UI and Foundation) version you use, check whether `AwaitPointerEventScope` has a way to await events in the Initial pass (e.g. `awaitPointerEvent(PointerEventPass.Initial)` or a similar overload). This is in `androidx.compose.ui.input.pointer` / foundation gestures.
2. **Wear + Mobile – CustomHorizontalPager / CustomVerticalPager:**
  - Remove all overlay and edge-strip UI (no extra Boxes for swipe; no `pointerInteropFilter`, no `SwipeDragState`, no `MotionEvent`, no `SWIPE_EDGE_WIDTH`).
  - On the **existing outer Box** (the one that has `onSizeChanged` and contains the pager + indicator), add a modifier that uses `pointerInput(pagerState, ...)` and inside `awaitPointerEventScope` runs a loop that awaits pointer events **in the Initial pass**, tracks `totalDrag`, **never** calls `consume()`, and on release calls `animateScrollToPage` when `|totalDrag| >= thresholdPx`.
  - Keep `userScrollEnabled = pagerUserScrollEnabled` with `pagerUserScrollEnabled = !useSwipeToPage && userScrollEnabled`.
  - Keep `SWIPE_THRESHOLD_FRACTION` and `SWIPE_THRESHOLD_MIN_DP`; drop constants/imports only used by the old overlay/strips.
3. If the **Initial-pass API is not available** in your Compose version, then with the current pointer model we **cannot** satisfy all of: no partial drag + clicks propagate + nested scroll. You would have to relax one (e.g. allow brief movement and snap back on release when below threshold).

## Summary


| Requirement                          | How it's met                                                                                  |
| ------------------------------------ | --------------------------------------------------------------------------------------------- |
| Page doesn't move when swipe is weak | Pager `userScrollEnabled = false`; we only call `animateScrollToPage` when drag >= threshold. |
| Clicks propagate                     | No overlay; parent observes in Initial pass and does not consume; child remains hit target.   |
| Nested scroll works                  | Same; events still go to the scrollable child.                                                |
| Swipe-to-page when strong enough     | Parent tracks drag in Initial pass; on release, if over threshold, animate to next/prev.      |


