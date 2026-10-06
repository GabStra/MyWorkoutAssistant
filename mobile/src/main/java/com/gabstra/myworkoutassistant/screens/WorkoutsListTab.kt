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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ContentTitle
import com.gabstra.myworkoutassistant.composables.AppAddButton
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Workout
import java.util.UUID

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
    onHideDisabledWorkoutsChange: (Boolean) -> Unit
) {
    val scrollState = key(selectedPlanId) { rememberScrollState() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(vertical = Spacing.md)
            .verticalScroll(scrollState)
            .padding(horizontal = Spacing.md)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            ContentTitle(
                text = "Workouts",
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
                            "Show $disabledWorkoutCount disabled"
                        } else {
                            "Hide disabled"
                        },
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
        }
        Spacer(Modifier.height(Spacing.md))
        if (workouts.isEmpty()) {
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
        } else {
            GenericSelectableList(
                items = workouts,
                selectedItems = selectedWorkouts,
                isSelectionModeActive = isSelectionModeActive,
                onItemClick = { workout ->
                    onWorkoutClick(workout)
                },
                onEnableSelection = {
                    onSelectionModeChange(true)
                },
                onDisableSelection = {
                    onSelectionModeChange(false)
                },
                onSelectionChange = { newSelection ->
                    onSelectionChange(newSelection)
                },
                onOrderChange = { },
                itemContent = { workout, onItemClick, onItemLongClick ->
                    StyledCard(
                        modifier = Modifier
                            .semantics { contentDescription = "Open workout: ${workout.name}" }
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
                },
                isDragDisabled = true,
                keySelector = { workout -> workout.id }
            )
        }
        Spacer(Modifier.height(Spacing.md))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            AppAddButton(
                onClick = {
                    appViewModel.setScreenData(
                        ScreenData.NewWorkout(selectedPlanId)
                    )
                }
            )
        }
    }
}
