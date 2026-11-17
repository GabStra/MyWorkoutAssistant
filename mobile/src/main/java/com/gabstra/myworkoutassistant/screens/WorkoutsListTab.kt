package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ContentTitle
import com.gabstra.myworkoutassistant.composables.AppAddButton
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.workout.presentation.orderWorkoutsForPresentation
import com.gabstra.myworkoutassistant.shared.workout.presentation.resolveRecurringPrescriptionProgress
import java.util.UUID

internal fun workoutsRepresentedByCard(card: Workout, currentWorkouts: List<Workout>): List<Workout> {
    val sessionId = card.recurringSessionId ?: return listOf(card)
    return currentWorkouts.filter { it.isActive && it.recurringSessionId == sessionId }
        .ifEmpty { listOf(card) }
}

internal fun expandWorkoutCardSelection(
    selectedCards: List<Workout>,
    currentWorkouts: List<Workout>,
): List<Workout> = selectedCards
    .flatMap { workoutsRepresentedByCard(it, currentWorkouts) }
    .distinctBy { it.id }

internal fun recurringPrescriptionDisplayLabel(workout: Workout, prescriptionWord: String): String =
    workout.prescriptionLabel?.takeIf { it.isNotBlank() }
        ?: workout.prescriptionOrdinal?.let { "$prescriptionWord $it" }
        ?: prescriptionWord

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutsListTab(
    workouts: List<Workout>,
    selectedWorkouts: List<Workout>,
    isSelectionModeActive: Boolean,
    appViewModel: AppViewModel,
    onWorkoutClick: (Workout) -> Unit,
    onSelectionChange: (List<Workout>) -> Unit,
    onSelectionModeChange: (Boolean) -> Unit,
    selectedPlanId: UUID? = null,
    hideDisabledWorkouts: Boolean,
    disabledWorkoutCount: Int,
    emptyMessage: String,
    onHideDisabledWorkoutsChange: (Boolean) -> Unit,
    onReorderRecurring: (List<Workout>, List<UUID>) -> Unit = { _, _ -> },
    onAddNextPrescription: (Workout, List<Workout>) -> Unit = { _, _ -> },
    workoutHistories: List<WorkoutHistory>? = null,
    suggestionEnabledByPlan: Map<UUID, Boolean> = emptyMap(),
    focusedRecurringSessionId: UUID? = null,
    onOpenRecurringSession: (UUID) -> Unit = {},
) {
    val scrollState = key(selectedPlanId) { rememberScrollState() }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(vertical = Spacing.md)
            .verticalScroll(scrollState)
            .padding(horizontal = Spacing.md)
            .then(
                focusedRecurringSessionId?.let { sessionId ->
                    Modifier.testTag("session_prescriptions_$sessionId")
                } ?: Modifier
            )
    ) {
        if (focusedRecurringSessionId == null) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
            ) {
                ContentTitle(
                    text = stringResource(R.string.workout_list_title),
                    modifier = Modifier.weight(1f),
                )
                if (disabledWorkoutCount > 0) {
                    TextButton(
                        onClick = { onHideDisabledWorkoutsChange(!hideDisabledWorkouts) },
                        contentPadding = PaddingValues(horizontal = Spacing.sm, vertical = 0.dp),
                    ) {
                        Icon(
                            imageVector = if (hideDisabledWorkouts) {
                                Icons.Default.Visibility
                            } else {
                                Icons.Default.VisibilityOff
                            },
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.size(Spacing.xs))
                        Text(
                            text = if (hideDisabledWorkouts) {
                                stringResource(R.string.workout_show_disabled_count, disabledWorkoutCount)
                            } else {
                                stringResource(R.string.workout_hide_disabled)
                            },
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                }
            }
            Spacer(Modifier.height(Spacing.md))
        }
        val displayedWorkouts = remember(workouts) { orderWorkoutsForPresentation(workouts) }
        val activeFamiliesBySession = remember(appViewModel.workouts) {
            appViewModel.workouts.filter { it.isActive && it.recurringSessionId != null }
                .groupBy { it.recurringSessionId!! }
        }
        val listWorkouts = remember(displayedWorkouts, focusedRecurringSessionId) {
            if (focusedRecurringSessionId != null) {
                displayedWorkouts.filter { it.recurringSessionId == focusedRecurringSessionId }
            } else {
                val seenSessions = mutableSetOf<UUID>()
                displayedWorkouts.filter { workout ->
                    workout.recurringSessionId?.let(seenSessions::add) ?: true
                }
            }
        }
        val focusedFamily = focusedRecurringSessionId?.let { sessionId ->
            (activeFamiliesBySession[sessionId]
                ?: displayedWorkouts.filter { it.recurringSessionId == sessionId })
                .sortedBy { it.prescriptionOrdinal ?: Int.MAX_VALUE }
        }.orEmpty()
        val focusedSessionName = focusedFamily.firstOrNull()?.name
            ?: focusedRecurringSessionId?.let { sessionId ->
                displayedWorkouts.firstOrNull { it.recurringSessionId == sessionId }?.name
            }
        val progressBySession = remember(displayedWorkouts, workoutHistories) {
            workoutHistories?.let { histories ->
                resolveRecurringPrescriptionProgress(
                    workouts = displayedWorkouts.filter { it.isActive && it.enabled },
                    histories = histories,
                )
            }.orEmpty()
        }

        if (workouts.isEmpty() && focusedRecurringSessionId == null) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(Spacing.xl),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = emptyMessage,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
            if (selectedPlanId != null) {
                Text(
                    text = stringResource(R.string.workout_create_first_hint),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = Spacing.md),
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        } else {
            if (focusedRecurringSessionId != null) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(Spacing.xs),
                ) {
                    val suggestionsEnabled = focusedFamily.firstOrNull()?.workoutPlanId
                        ?.let { suggestionEnabledByPlan[it] } == true
                    val progress = progressBySession[focusedRecurringSessionId]
                        .takeIf { workoutHistories != null }
                    progress?.lastCompletedWorkoutId?.let { completedId ->
                        focusedFamily.firstOrNull { it.id == completedId }?.let { completed ->
                            Text(stringResource(R.string.workout_last_completed, recurringPrescriptionDisplayLabel(completed, stringResource(R.string.prescription))))
                        }
                    }
                    if (suggestionsEnabled) {
                        progress?.suggestedWorkoutId?.let { suggestedId ->
                            focusedFamily.firstOrNull { it.id == suggestedId }?.let { suggested ->
                                TextButton(
                                    modifier = Modifier.testTag("suggested_next_prescription"),
                                    onClick = { onWorkoutClick(suggested) },
                                ) {
                                    Text(stringResource(R.string.workout_suggested_next, recurringPrescriptionDisplayLabel(suggested, stringResource(R.string.prescription))))
                                }
                            }
                        }
                        if (progress?.reachedEnd == true) {
                            Text(stringResource(R.string.workout_end_of_sequence))
                            focusedFamily.firstOrNull { it.id == progress.firstWorkoutId }?.let { firstWorkout ->
                                TextButton(onClick = { onWorkoutClick(firstWorkout) }) {
                                    Text(stringResource(R.string.workout_repeat_sequence))
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(Spacing.xs))
            }

            if (listWorkouts.isEmpty()) {
                Text(
                    text = emptyMessage,
                    modifier = Modifier.fillMaxWidth().padding(Spacing.xl),
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            } else {
            val selectedIds = selectedWorkouts.mapTo(mutableSetOf()) { it.id }
            val selectedListItems = if (focusedRecurringSessionId != null) {
                listWorkouts.filter { it.id in selectedIds }
            } else {
                listWorkouts.filter { card ->
                    workoutsRepresentedByCard(card, appViewModel.workouts)
                        .all { it.id in selectedIds }
                }
            }
            GenericSelectableList(
                items = listWorkouts,
                selectedItems = selectedListItems,
                isSelectionModeActive = isSelectionModeActive,
                onItemClick = { workout ->
                    val sessionId = workout.recurringSessionId
                    if (focusedRecurringSessionId == null && sessionId != null) {
                        onOpenRecurringSession(sessionId)
                    } else {
                        onWorkoutClick(workout)
                    }
                },
                onEnableSelection = {
                    onSelectionModeChange(true)
                },
                onDisableSelection = {
                    onSelectionModeChange(false)
                },
                onSelectionChange = { newSelection ->
                    if (focusedRecurringSessionId != null) {
                        onSelectionChange(newSelection)
                    } else if (newSelection.isEmpty()) {
                        onSelectionChange(emptyList())
                    } else {
                        val priorCardIds = selectedListItems.mapTo(mutableSetOf()) { it.id }
                        val nextCardIds = newSelection.mapTo(mutableSetOf()) { it.id }
                        val changedCardIds = (priorCardIds + nextCardIds).filterTo(mutableSetOf()) { id ->
                            (id in priorCardIds) != (id in nextCardIds)
                        }
                        val changedCards = listWorkouts.filter { it.id in changedCardIds }
                        val changedWorkoutIds = changedCards
                            .flatMap { workoutsRepresentedByCard(it, appViewModel.workouts) }
                            .mapTo(mutableSetOf()) { it.id }
                        val preserved = selectedWorkouts.filterNot { it.id in changedWorkoutIds }
                        val newlySelected = changedCards.filter { it.id in nextCardIds }
                        onSelectionChange(
                            (preserved + expandWorkoutCardSelection(newlySelected, appViewModel.workouts))
                                .distinctBy { it.id }
                        )
                    }
                },
                onOrderChange = { orderedWorkouts ->
                    if (focusedRecurringSessionId != null) {
                        onReorderRecurring(focusedFamily, orderedWorkouts.map { it.id })
                    }
                },
                itemContent = { workout, onItemClick, onItemLongClick ->
                    val sessionId = workout.recurringSessionId
                    val isRootSessionCard = focusedRecurringSessionId == null && sessionId != null
                    val sessionFamily = sessionId?.let { activeFamiliesBySession[it] }
                        ?: sessionId?.let { id -> displayedWorkouts.filter { it.recurringSessionId == id } }
                        ?: emptyList()
                    val prescriptionText = recurringPrescriptionDisplayLabel(workout, stringResource(R.string.prescription))
                    val itemContentDescription = when {
                        isRootSessionCard -> stringResource(R.string.workout_open_session_cd, workout.name)
                        focusedRecurringSessionId != null && sessionId != null -> stringResource(
                            R.string.workout_open_prescription_in_session_cd,
                            prescriptionText,
                            focusedSessionName ?: workout.name,
                        )
                        else -> stringResource(R.string.workout_open_workout_cd, workout.name)
                    }
                    StyledCard(
                        modifier = Modifier
                            .semantics {
                                contentDescription = itemContentDescription
                            }
                            .then(
                                if (isRootSessionCard) Modifier.testTag("recurring_session_$sessionId")
                                else if (focusedRecurringSessionId != null && sessionId != null) Modifier.testTag("prescription_${workout.id}")
                                else Modifier
                            )
                            .combinedClickable(
                                onClick = {
                                    onItemClick()
                                },
                                onLongClick = {
                                    onItemLongClick()
                                }
                            ),
                        enabled = workout.enabled
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(Spacing.md),
                            verticalArrangement = Arrangement.spacedBy(Spacing.xs)
                        ) {
                            if (isRootSessionCard) {
                                val count = sessionFamily.size
                                Text(
                                    modifier = Modifier.fillMaxWidth(),
                                    text = workout.name,
                                    color = if (workout.enabled) MaterialTheme.colorScheme.onSurface else DisabledContentGray,
                                    style = MaterialTheme.typography.bodyLarge,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    text = pluralStringResource(R.plurals.workout_prescription_count, count, count),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            } else if (focusedRecurringSessionId != null && sessionId != null) {
                                Text(
                                    text = prescriptionText,
                                    color = MaterialTheme.colorScheme.primary,
                                    style = MaterialTheme.typography.bodyLarge,
                                )
                                if (workout.description.isNotBlank()) {
                                    Text(
                                        modifier = Modifier.fillMaxWidth(),
                                        text = workout.description,
                                        color = if (workout.enabled) MaterialTheme.colorScheme.onSurfaceVariant else DisabledContentGray,
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                }
                            } else {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .basicMarquee(iterations = Int.MAX_VALUE),
                                    text = workout.name,
                                    color = if (workout.enabled) MaterialTheme.colorScheme.onSurface else DisabledContentGray,
                                    style = MaterialTheme.typography.bodyLarge,
                                    maxLines = 2
                                )
                                if (workout.description.isNotEmpty()) {
                                    Text(
                                        modifier = Modifier.fillMaxWidth(),
                                        text = workout.description,
                                        color = if (workout.enabled) MaterialTheme.colorScheme.onSurfaceVariant else DisabledContentGray,
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                }
                            }
                        }
                    }
                },
                isDragDisabled = focusedRecurringSessionId != null,
                keySelector = { workout -> workout.id }
            )
        }
        }
        Spacer(Modifier.height(Spacing.md))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (focusedRecurringSessionId != null) {
                AppAddButton(
                    modifier = Modifier.testTag("add_prescription"),
                    label = stringResource(R.string.workout_add_prescription),
                    onClick = {
                        focusedFamily.lastOrNull()?.let { onAddNextPrescription(it, focusedFamily) }
                    },
                    enabled = focusedFamily.isNotEmpty(),
                )
            } else AppAddButton(
                onClick = {
                    appViewModel.setScreenData(
                        ScreenData.NewWorkout(selectedPlanId)
                    )
                }
            )
            }
    }
}
