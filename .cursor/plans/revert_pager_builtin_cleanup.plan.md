---
name: ""
overview: ""
todos: []
isProject: false
---

# Revert to built-in pager and clean up

## Goal

Use the **built-in** scroll/fling of `HorizontalPager` and `VerticalPager` with no custom swipe handling. Remove all overlay, edge-strip, threshold, and related code.

## Changes per file

### 1. Wear OS – [CustomHorizontalPager.kt](wearos/src/main/java/com/gabstra/myworkoutassistant/composables/CustomHorizontalPager.kt)

**Remove**

- Constants: `SWIPE_THRESHOLD_FRACTION`, `SWIPE_THRESHOLD_MIN_DP`, `SWIPE_EDGE_WIDTH`
- Class: `SwipeDragState`
- Function: `observeSwipeToPage` (entire `Modifier.pointerInteropFilter` block)
- In composable: `pageSizePx`, `useSwipeToPage`, `pagerUserScrollEnabled`, `thresholdPx`
- The entire `if (useSwipeToPage) { ... }` block (both edge-strip `Box`es)
- From the outer `Box`: `onSizeChanged` (only used for `pageSizePx` → threshold)

**Set**

- `HorizontalPager`: `userScrollEnabled = userScrollEnabled` (remove `pagerUserScrollEnabled`)
- Outer `Box`: `modifier = modifier` (no `onSizeChanged`)

**Imports to remove**

- `ExperimentalComposeUiApi`, `pointerInteropFilter`, `android.view.MotionEvent`
- `fillMaxHeight`, `width` (if only used by edge strips)
- `LocalDensity` (if only used for `thresholdPx`)
- `mutableFloatStateOf` (if only used for `pageSizePx`)

**Keep**

- Indicator, `CustomAnimatedPage`, `PagerDefaults.snapFlingBehavior`, `clip`, etc.

---

### 2. Wear OS – [CustomVerticalPager.kt](wearos/src/main/java/com/gabstra/myworkoutassistant/composables/CustomVerticalPager.kt)

**Remove**

- `pageSizePx`, `useSwipeToPage`, `pagerUserScrollEnabled`, `thresholdPx`
- The entire `if (useSwipeToPage) { ... }` block (both edge-strip `Box`es)
- From the outer `Box`: `onSizeChanged`

**Set**

- `VerticalPager`: `userScrollEnabled = userScrollEnabled`
- Outer `Box`: `modifier = modifier`

**Imports to remove**

- `fillMaxWidth`, `height` (if only used by edge strips)
- `LocalDensity`, `mutableFloatStateOf` (if only used for threshold/pageSizePx)

**Remove constants** (if present here)

- `SWIPE_THRESHOLD_FRACTION`, `SWIPE_THRESHOLD_MIN_DP` (used only for removed overlay)

---

### 3. Mobile – [CustomHorizontalPager.kt](mobile/src/main/java/com/gabstra/myworkoutassistant/workout/CustomHorizontalPager.kt)

**Remove**

- Constants: `SWIPE_THRESHOLD_FRACTION`, `SWIPE_THRESHOLD_MIN_DP`, `SWIPE_EDGE_WIDTH`
- Class: `SwipeDragState`
- Function: `observeSwipeToPage`
- In composable: `pageSizePx`, `useSwipeToPage`, `pagerUserScrollEnabled`, `thresholdPx`
- The entire `if (useSwipeToPage) { ... }` block (both edge-strip `Box`es)
- From the outer `Box`: `onSizeChanged`

**Set**

- `HorizontalPager`: `userScrollEnabled = userScrollEnabled`
- Outer `Box`: `modifier = modifier`

**Imports to remove**

- `ExperimentalComposeUiApi`, `pointerInteropFilter`, `android.view.MotionEvent`
- `fillMaxHeight`, `width`
- `LocalDensity`, `mutableFloatStateOf` (if only used for threshold/pageSizePx)

---

### 4. Mobile – [CustomVerticalPager.kt](mobile/src/main/java/com/gabstra/myworkoutassistant/workout/CustomVerticalPager.kt)

**Remove**

- Constants: `SWIPE_THRESHOLD_FRACTION`, `SWIPE_THRESHOLD_MIN_DP`
- `pageSizePx`, `useSwipeToPage`, `pagerUserScrollEnabled`, `thresholdPx`
- The entire `if (useSwipeToPage) { ... }` block (both edge-strip `Box`es)
- From the outer `Box`: `onSizeChanged`

**Set**

- `VerticalPager`: `userScrollEnabled = userScrollEnabled`
- Outer `Box`: `modifier = modifier`

**Imports to remove**

- `fillMaxWidth`, `height`
- `LocalDensity`, `mutableFloatStateOf` (if only used for threshold/pageSizePx)

---

## Verification

- `./gradlew :wearos:assembleDebug :mobile:assembleDebug`
- No references to `SwipeDragState`, `observeSwipeToPage`, `SWIPE_EDGE_WIDTH`, `SWIPE_THRESHOLD_*` (except any remaining comments you keep)
- Pagers use built-in scroll and default fling only

