package com.gabstra.myworkoutassistant

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.BreadcrumbTrail
import com.gabstra.myworkoutassistant.composables.BreadcrumbTrailItem
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.allExercisePrescriptions
import com.gabstra.myworkoutassistant.shared.equipments.toDisplayText
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
    val items = remember(stack, store) { buildBreadcrumbItems(stack, store).dropLast(1) }
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
    stack: List<ScreenData>,
    store: WorkoutStore,
): List<BreadcrumbItem> {
    val exercises = store.allExercisePrescriptions().associateBy { it.id }
    val result = mutableListOf<BreadcrumbItem>()
    var insertedPlanId: UUID? = null
    stack.forEach { screen ->
        val workoutId = screen.workoutIdOrNull()
        val plan = if (screen is ScreenData.NewWorkout) {
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
        result += BreadcrumbItem(screen.breadcrumbLabel(store, exercises), screen = screen)
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
    store: WorkoutStore,
    exercises: Map<UUID, com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>,
): String = when (this) {
    is ScreenData.Workouts -> listOf("Status", "Workouts", "Exercise Library", "Alarms", "Gear")
        .getOrElse(selectedTabIndex) { "Home" }
    is ScreenData.Settings -> "Settings"
    is ScreenData.ErrorLogs -> "Error logs"
    is ScreenData.NewWorkout -> "New workout"
    is ScreenData.Workout -> store.workouts.firstOrNull { it.id == workoutId }?.name ?: "Workout"
    is ScreenData.EditWorkout -> "Edit workout"
    is ScreenData.WorkoutDetail -> store.workouts.firstOrNull { it.id == workoutId }?.name ?: "Workout"
    is ScreenData.WorkoutHistory -> "History"
    is ScreenData.ExternalWorkoutSession -> "External session"
    is ScreenData.ExerciseDetail -> exercises[selectedExerciseId]?.name ?: "Exercise"
    is ScreenData.ExerciseHistory -> "History"
    is ScreenData.HistoryChatExercise, is ScreenData.HistoryChatWorkoutSession -> "History chat"
    is ScreenData.NewExercise -> if (exerciseDefinitionId == null && !skipLibrary) "Choose exercise" else "Prescription"
    is ScreenData.EditExercise -> "Edit prescription"
    is ScreenData.NewExerciseDefinition -> "New definition"
    is ScreenData.EditExerciseDefinition -> store.exerciseDefinitions
        .firstOrNull { it.id == exerciseDefinitionId }?.name ?: "Edit definition"
    is ScreenData.NewSuperset -> "New superset"
    is ScreenData.EditSuperset -> "Edit superset"
    is ScreenData.NewRest -> "New rest"
    is ScreenData.EditRest -> "Edit rest"
    is ScreenData.NewRestSet -> "New rest set"
    is ScreenData.EditRestSet -> "Edit rest set"
    is ScreenData.InsertRestSetAfter -> "Insert rest set"
    is ScreenData.InsertRestAfter -> "Insert rest"
    is ScreenData.NewSet -> "New set"
    is ScreenData.EditSet -> "Edit set"
    is ScreenData.NewEquipment -> "New ${equipmentType.toDisplayText().lowercase()}"
    is ScreenData.EditEquipment -> "Edit ${equipmentType.toDisplayText().lowercase()}"
}
