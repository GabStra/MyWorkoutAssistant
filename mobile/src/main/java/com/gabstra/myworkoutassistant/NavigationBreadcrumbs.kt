package com.gabstra.myworkoutassistant

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.BreadcrumbTrail
import com.gabstra.myworkoutassistant.composables.BreadcrumbTrailItem
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.allExercisePrescriptions
import java.util.UUID

private data class BreadcrumbItem(
    val label: String,
    val screen: ScreenData? = null,
    val planId: UUID? = null,
)

@Composable
fun NavigationBreadcrumbs(
    appViewModel: AppViewModel,
    showOnDefinitionEditor: Boolean = false,
) {
    val stack = appViewModel.navigationStack()
    val context = LocalContext.current
    val currentScreen = stack.lastOrNull()
    if (
        !showOnDefinitionEditor &&
        (currentScreen is ScreenData.NewExerciseDefinition ||
            currentScreen is ScreenData.EditExerciseDefinition)
    ) {
        return
    }
    if (stack.size <= 1) return
    val store = appViewModel.workoutStore
    val showCurrentRecurringPath = when (currentScreen) {
        is ScreenData.SessionPrescriptions -> true
        is ScreenData.WorkoutDetail -> store.workouts
            .firstOrNull { it.id == currentScreen.workoutId }
            ?.recurringSessionId != null
        else -> false
    }
    val items = remember(context, stack, store, showCurrentRecurringPath) {
        val breadcrumbs = buildBreadcrumbItems(context, stack, store)
        if (showCurrentRecurringPath) breadcrumbs else breadcrumbs.dropLast(1)
    }
    if (items.isEmpty()) return
    val scrollState = rememberScrollState()

    BreadcrumbTrail(
        items = items.map { item ->
            BreadcrumbTrailItem(
                label = item.label,
                onClick = {
                    when {
                        item.planId != null -> appViewModel.openWorkoutPlanFromBreadcrumb(item.planId)
                        item.screen != null -> appViewModel.popToScreen(item.screen)
                    }
                },
            )
        },
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(scrollState)
            .padding(horizontal = 16.dp, vertical = 8.dp),
    )
}

private fun buildBreadcrumbItems(
    context: android.content.Context,
    stack: List<ScreenData>,
    store: WorkoutStore,
): List<BreadcrumbItem> {
    val exercises = store.allExercisePrescriptions().associateBy { it.id }
    val result = mutableListOf<BreadcrumbItem>()
    var insertedPlanId: UUID? = null
    stack.forEach { screen ->
        val workoutId = screen.workoutIdOrNull()
        val plan = if (screen is ScreenData.SessionPrescriptions) {
            store.workouts.firstOrNull {
                it.isActive && it.recurringSessionId == screen.sessionId
            }?.workoutPlanId?.let { planId -> store.workoutPlans.firstOrNull { it.id == planId } }
        } else if (screen is ScreenData.NewWorkout) {
            screen.workoutPlanId?.let { planId ->
                store.workoutPlans.firstOrNull { it.id == planId }
            }
        } else if (workoutId != null) {
            val workout = store.workouts.firstOrNull { it.id == workoutId }
            workout?.workoutPlanId?.let { planId ->
                store.workoutPlans.firstOrNull { it.id == planId }
            }
        } else {
            null
        }
        if (plan != null && insertedPlanId != plan.id) {
            result += BreadcrumbItem(plan.name, planId = plan.id)
            insertedPlanId = plan.id
        }
        result += BreadcrumbItem(screen.breadcrumbLabel(context, store, exercises), screen = screen)
    }
    return result
}

private fun ScreenData.workoutIdOrNull(): UUID? = when (this) {
    is ScreenData.Workout -> workoutId
    is ScreenData.EditWorkout -> workoutId
    is ScreenData.WorkoutDetail -> workoutId
    is ScreenData.WorkoutHistory -> workoutId
    is ScreenData.ExerciseDetail -> workoutId
    is ScreenData.ExerciseHistory -> workoutId
    is ScreenData.HistoryChatExercise -> workoutId
    is ScreenData.HistoryChatWorkoutSession -> workoutId
    is ScreenData.NewExercise -> workoutId
    is ScreenData.EditExercise -> workoutId
    is ScreenData.NewSuperset -> workoutId
    is ScreenData.EditSuperset -> workoutId
    is ScreenData.NewRest -> workoutId
    is ScreenData.EditRest -> workoutId
    is ScreenData.NewRestSet -> workoutId
    is ScreenData.EditRestSet -> workoutId
    is ScreenData.InsertRestSetAfter -> workoutId
    is ScreenData.InsertRestAfter -> workoutId
    is ScreenData.NewSet -> workoutId
    is ScreenData.EditSet -> workoutId
    else -> null
}

private fun ScreenData.breadcrumbLabel(
    context: android.content.Context,
    store: WorkoutStore,
    exercises: Map<UUID, com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>,
): String = when (this) {
    is ScreenData.Workouts -> listOf(
        context.getString(R.string.loc_scr_breadcrumb_status),
        context.getString(R.string.loc_scr_breadcrumb_workouts),
        context.getString(R.string.loc_scr_breadcrumb_exercise_library),
        context.getString(R.string.loc_scr_breadcrumb_alarms),
        context.getString(R.string.loc_scr_breadcrumb_gear),
    ).getOrElse(selectedTabIndex) { context.getString(R.string.loc_scr_tab_home) }
    is ScreenData.Plans -> context.getString(R.string.loc_plans)
    is ScreenData.SessionPrescriptions -> store.workouts.firstOrNull {
        it.isActive && it.recurringSessionId == sessionId
    }?.name ?: context.getString(R.string.loc_scr_recurring_session)
    is ScreenData.Settings -> context.getString(R.string.loc_settings_cd)
    is ScreenData.ErrorLogs -> context.getString(R.string.loc_scr_error_logs)
    is ScreenData.NewWorkout -> context.getString(R.string.loc_scr_new_workout)
    is ScreenData.Workout -> store.workouts.firstOrNull { it.id == workoutId }?.name
        ?: context.getString(R.string.loc_scr_workout)
    is ScreenData.EditWorkout -> context.getString(R.string.workout_form_edit_title)
    is ScreenData.WorkoutDetail -> store.workouts.firstOrNull { it.id == workoutId }?.let { workout ->
        if (workout.recurringSessionId != null) {
            workout.prescriptionLabel
                ?: workout.prescriptionOrdinal?.let { context.getString(R.string.loc_scr_prescription_n, it) }
                ?: context.getString(R.string.prescription)
        } else {
            workout.name
        }
    } ?: context.getString(R.string.loc_scr_workout)
    is ScreenData.WorkoutHistory -> context.getString(R.string.loc_scr_history)
    is ScreenData.ExternalWorkoutSession -> context.getString(R.string.loc_scr_external_session)
    is ScreenData.SensorSessions -> context.getString(R.string.loc_scr_sensor_sessions)
    is ScreenData.SensorSessionDetail -> context.getString(R.string.loc_scr_sensor_session)
    is ScreenData.ExerciseDetail -> exercises[selectedExerciseId]?.name
        ?: context.getString(R.string.loc_scr_exercise)
    is ScreenData.ExerciseHistory -> context.getString(R.string.loc_scr_history)
    is ScreenData.HistoryChatExercise, is ScreenData.HistoryChatWorkoutSession ->
        context.getString(R.string.loc_scr_history_chat)
    is ScreenData.NewExercise -> if (exerciseDefinitionId == null && !skipLibrary) {
        context.getString(R.string.loc_scr_choose_exercise)
    } else {
        context.getString(R.string.prescription)
    }
    is ScreenData.EditExercise -> context.getString(R.string.loc_scr_edit_prescription)
    is ScreenData.NewExerciseDefinition -> context.getString(R.string.loc_scr_new_definition)
    is ScreenData.EditExerciseDefinition -> store.exerciseDefinitions
        .firstOrNull { it.id == exerciseDefinitionId }?.name
        ?: context.getString(R.string.loc_scr_edit_definition)
    is ScreenData.NewSuperset -> context.getString(R.string.loc_scr_new_superset)
    is ScreenData.EditSuperset -> context.getString(R.string.loc_scr_edit_superset)
    is ScreenData.NewRest -> context.getString(R.string.loc_scr_new_rest)
    is ScreenData.EditRest -> context.getString(R.string.loc_scr_edit_rest)
    is ScreenData.NewRestSet -> context.getString(R.string.loc_scr_new_rest_set)
    is ScreenData.EditRestSet -> context.getString(R.string.loc_scr_edit_rest_set)
    is ScreenData.InsertRestSetAfter -> context.getString(R.string.loc_scr_insert_rest_set)
    is ScreenData.InsertRestAfter -> context.getString(R.string.loc_scr_insert_rest)
    is ScreenData.NewSet -> context.getString(R.string.loc_scr_new_set)
    is ScreenData.EditSet -> context.getString(R.string.loc_scr_edit_set)
    is ScreenData.NewEquipment -> context.getString(
        R.string.loc_scr_new_equipment,
        equipmentType.localizedLabel(context).lowercase(),
    )
    is ScreenData.EditEquipment -> context.getString(
        R.string.loc_scr_edit_equipment,
        equipmentType.localizedLabel(context).lowercase(),
    )
}
