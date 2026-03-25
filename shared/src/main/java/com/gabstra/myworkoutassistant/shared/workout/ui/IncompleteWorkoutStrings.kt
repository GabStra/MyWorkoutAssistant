package com.gabstra.myworkoutassistant.shared.workout.ui

/** User-visible strings for incomplete workouts and related flows (mobile + Wear). */
object IncompleteWorkoutStrings {
    const val SINGULAR = "Incomplete workout"
    const val PLURAL = "Incomplete workouts"
    const val SUFFIX = "(Incomplete)"

    const val RESUME_DIALOG_DESCRIPTION =
        "You have workouts that weren't completed. Select one to resume:"

    const val DISCARD_BUTTON = "Discard"

    const val DELETE_BUTTON = "Delete"
    const val DELETE_TITLE = "Remove incomplete workout"
    const val DELETE_MESSAGE = "Remove this workout that wasn't completed?"
    const val START_NEW_WORKOUT_MESSAGE =
        "An open session will be removed. Continue?"

    const val CLEAR_MENU_LABEL = "Clear incomplete workouts"
    const val CLEAR_TITLE = "Clear all incomplete workouts"
    const val CLEAR_MESSAGE =
        "Remove every workout that wasn't completed (stale watch data or after exiting " +
            "without finishing). This can't be undone."

    /** Recovery dialog body on Wear (resume vs discard). */
    const val RECOVERY_RESUME_OR_DISCARD_BODY =
        "Resume or discard this incomplete workout."

    /** Wear recovery: section headers (avoid “recovery” as user-facing jargon). */
    const val RECOVERY_SECTION_TIMER = "Timer"
    const val RECOVERY_SECTION_CALIBRATION = "Calibration"

    /** Wear loading line (animated dots may be appended in the Wear UI). */
    const val CHECKING_SESSION_PROGRESS = "Checking session"

    const val CHECKING_SESSION = "Checking session…"

    /** Wear: confirming start when an incomplete session exists. */
    const val START_NEW_WORKOUT_TITLE = "Start a new workout"
}
