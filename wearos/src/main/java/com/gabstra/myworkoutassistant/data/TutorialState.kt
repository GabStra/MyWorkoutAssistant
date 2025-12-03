package com.gabstra.myworkoutassistant.data

import android.content.Context

/**
 * Simple container for tutorial / onboarding progress on Wear OS.
 *
 * This is intentionally lightweight and backed by SharedPreferences so it can
 * be used safely from composables via callbacks.
 *
 * How to add a new tutorial:
 * - Add a new Boolean property to [TutorialState]
 * - Add a matching key constant below
 * - Read/write it in [load] and [update]
 * - Thread the flag through `WearApp` and the relevant screen as a parameter
 * - Use `TutorialOverlay` (or a custom composable) controlled by that flag
 *
 * References for patterns:
 * - Official Wear OS Compose samples: https://github.com/android/wear-os-samples (e.g. ComposeStarter)
 * - Coach-mark libraries used as inspiration: github.com/svenjacobs/reveal, github.com/ankitk77/coachmark
 */
data class TutorialState(
    val hasSeenWorkoutSelectionTutorial: Boolean = false,
    val hasSeenWorkoutHeartRateTutorial: Boolean = false,
    val hasSeenSetScreenTutorial: Boolean = false,
    val hasSeenRestScreenTutorial: Boolean = false,
)

object TutorialPreferences {
    private const val PREFS_NAME = "tutorial_prefs"
    private const val KEY_HAS_SEEN_WORKOUT_SELECTION = "has_seen_workout_selection_tutorial"
    private const val KEY_HAS_SEEN_WORKOUT_HEART_RATE = "has_seen_workout_heart_rate_tutorial"
    private const val KEY_HAS_SEEN_SET_SCREEN = "has_seen_set_screen_tutorial"
    private const val KEY_HAS_SEEN_REST_SCREEN = "has_seen_rest_screen_tutorial"

    fun load(context: Context): TutorialState {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return TutorialState(
            hasSeenWorkoutSelectionTutorial = prefs.getBoolean(KEY_HAS_SEEN_WORKOUT_SELECTION, false),
            hasSeenWorkoutHeartRateTutorial = prefs.getBoolean(KEY_HAS_SEEN_WORKOUT_HEART_RATE, false),
            hasSeenSetScreenTutorial = prefs.getBoolean(KEY_HAS_SEEN_SET_SCREEN, false),
            hasSeenRestScreenTutorial = prefs.getBoolean(KEY_HAS_SEEN_REST_SCREEN, false),
        )
    }

    fun update(
        context: Context,
        current: TutorialState,
        transform: (TutorialState) -> TutorialState
    ): TutorialState {
        val updated = transform(current)
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit()
            .putBoolean(KEY_HAS_SEEN_WORKOUT_SELECTION, updated.hasSeenWorkoutSelectionTutorial)
            .putBoolean(KEY_HAS_SEEN_WORKOUT_HEART_RATE, updated.hasSeenWorkoutHeartRateTutorial)
            .putBoolean(KEY_HAS_SEEN_SET_SCREEN, updated.hasSeenSetScreenTutorial)
            .putBoolean(KEY_HAS_SEEN_REST_SCREEN, updated.hasSeenRestScreenTutorial)
            .apply()
        return updated
    }
}

