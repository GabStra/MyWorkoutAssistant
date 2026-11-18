package com.gabstra.myworkoutassistant.screens

import android.content.Context
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.RecurringWorkoutAuthoringErrorCode
import com.gabstra.myworkoutassistant.shared.RecurringWorkoutAuthoringException
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRecurringMetadataIssue
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRecurringMetadataIssueCode
import com.gabstra.myworkoutassistant.shared.WorkoutStoreValidationException

private const val DUPLICATE_SET_ID_PREVIEW_LIMIT = 3
private const val RECURRING_METADATA_PREVIEW_LIMIT = 5

private fun RecurringWorkoutAuthoringErrorCode.messageResId(): Int = when (this) {
    RecurringWorkoutAuthoringErrorCode.WORKOUT_ALREADY_IN_RECURRING_SESSION ->
        R.string.loc_recurring_error_already_in_session
    RecurringWorkoutAuthoringErrorCode.DETACH_BEFORE_ATTACH ->
        R.string.loc_recurring_error_detach_before_attach
    RecurringWorkoutAuthoringErrorCode.SOURCE_NOT_IN_RECURRING_SESSION ->
        R.string.loc_recurring_error_source_not_in_session
    RecurringWorkoutAuthoringErrorCode.EMPTY_SESSION_NAME ->
        R.string.loc_recurring_error_empty_session_name
    RecurringWorkoutAuthoringErrorCode.WORKOUT_NOT_IN_RECURRING_SESSION ->
        R.string.loc_recurring_error_workout_not_in_session
    RecurringWorkoutAuthoringErrorCode.REORDER_INCOMPLETE ->
        R.string.loc_recurring_error_reorder_incomplete
    RecurringWorkoutAuthoringErrorCode.WORKOUT_NOT_RECURRING_FOR_TRACK ->
        R.string.loc_recurring_error_workout_not_recurring_for_track
    RecurringWorkoutAuthoringErrorCode.LOAD_POLICY_UNSUPPORTED ->
        R.string.loc_recurring_error_load_policy_unsupported
    RecurringWorkoutAuthoringErrorCode.EXERCISE_NOT_IN_WORKOUT ->
        R.string.loc_recurring_error_exercise_not_in_workout
    RecurringWorkoutAuthoringErrorCode.INCOMPATIBLE_TRACK ->
        R.string.loc_recurring_error_incompatible_track
    RecurringWorkoutAuthoringErrorCode.NO_ACTIVE_PRESCRIPTIONS ->
        R.string.loc_recurring_error_no_active_prescriptions
    RecurringWorkoutAuthoringErrorCode.MIXED_RECURRING_SESSIONS ->
        R.string.loc_recurring_error_mixed_sessions
}

/**
 * Resolves recurring-authoring failures to localized text while preserving the
 * message of any unrelated exception raised by the same operation.
 *
 * [WorkoutStoreValidationException] carries English developer diagnostics and must
 * never surface those through [Throwable.message]; its structured issues are
 * rendered through localized resources instead.
 */
internal fun recurringAuthoringErrorMessage(
    context: Context,
    error: Throwable,
    fallbackResId: Int,
): String = when (error) {
    is RecurringWorkoutAuthoringException -> context.getString(error.code.messageResId())
    is WorkoutStoreValidationException ->
        error.toLocalizedUserMessage(context).ifBlank { context.getString(fallbackResId) }
    else -> error.message ?: context.getString(fallbackResId)
}

internal fun WorkoutStoreValidationException.toLocalizedUserMessage(context: Context): String {
    val sections = mutableListOf<String>()
    if (duplicateSetIdIssues.isNotEmpty()) {
        sections += buildString {
            append(context.getString(R.string.loc_validation_duplicate_set_ids_intro))
            append("\n\n")
            append(
                duplicateSetIdIssues.take(DUPLICATE_SET_ID_PREVIEW_LIMIT).joinToString("\n\n") { issue ->
                    context.getString(
                        R.string.loc_validation_duplicate_set_id_block,
                        issue.workoutName,
                        issue.setId.toString(),
                        issue.exerciseNames.joinToString(", "),
                    )
                }
            )
            val remaining = duplicateSetIdIssues.size - DUPLICATE_SET_ID_PREVIEW_LIMIT
            if (remaining > 0) {
                append("\n\n")
                append(context.getString(R.string.loc_validation_duplicate_set_ids_more, remaining))
            }
        }
    }
    if (recurringMetadataIssues.isNotEmpty()) {
        sections += buildString {
            append(context.getString(R.string.loc_validation_recurring_intro))
            append("\n")
            append(
                recurringMetadataIssues.take(RECURRING_METADATA_PREVIEW_LIMIT).joinToString("\n") { issue ->
                    context.getString(
                        R.string.loc_validation_recurring_issue_line,
                        issue.toLocalizedText(context),
                    )
                }
            )
            val remaining = recurringMetadataIssues.size - RECURRING_METADATA_PREVIEW_LIMIT
            if (remaining > 0) {
                append("\n")
                append(context.getString(R.string.loc_validation_recurring_more, remaining))
            }
        }
    }
    return sections.joinToString("\n\n")
}

private fun WorkoutStoreRecurringMetadataIssue.toLocalizedText(context: Context): String =
    when (code) {
        WorkoutStoreRecurringMetadataIssueCode.FIXED_PRESCRIBED_LOAD_UNSUPPORTED_SETS ->
            context.getString(
                R.string.loc_validation_recurring_fixed_prescribed_load_unsupported,
                workoutName,
                exerciseName.orEmpty(),
            )
        WorkoutStoreRecurringMetadataIssueCode.MISSING_RECURRING_SESSION_ID ->
            context.getString(
                R.string.loc_validation_recurring_missing_session_id,
                workoutName,
            )
        WorkoutStoreRecurringMetadataIssueCode.NON_POSITIVE_PRESCRIPTION_ORDINAL ->
            context.getString(
                R.string.loc_validation_recurring_non_positive_ordinal,
                workoutName,
            )
        WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_PRESCRIPTION_ORDINAL ->
            context.getString(
                R.string.loc_validation_recurring_duplicate_ordinal,
                workoutName,
                prescriptionOrdinal ?: 0,
            )
        WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_RECURRING_EXERCISE_SLOT_IDS ->
            context.getString(
                R.string.loc_validation_recurring_duplicate_slot_ids,
                workoutName,
            )
        WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_MISSING_SLOT_ID ->
            context.getString(
                R.string.loc_validation_recurring_last_load_missing_slot_id,
                workoutName,
                exerciseName.orEmpty(),
            )
        WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_UNSUPPORTED_SETS ->
            context.getString(
                R.string.loc_validation_recurring_last_load_unsupported_sets,
                workoutName,
                exerciseName.orEmpty(),
            )
        WorkoutStoreRecurringMetadataIssueCode.CONFLICTING_RECURRING_SLOT_IDENTITY ->
            context.getString(
                R.string.loc_validation_recurring_conflicting_slot_identity,
                recurringExerciseSlotId?.toString().orEmpty(),
            )
    }
