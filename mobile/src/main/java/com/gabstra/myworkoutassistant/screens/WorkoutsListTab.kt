package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
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
    selectedPlanId: UUID? = null
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(vertical = 10.dp)
            .padding(horizontal = 15.dp)
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Workouts:",
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onBackground
        )

        if (workouts.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(15.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "No workouts in this plan",
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                )
            }
        } else {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            ) {
                GenericSelectableList(
                    it = PaddingValues(0.dp, 10.dp),
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
                                    .padding(15.dp),
                                verticalArrangement = Arrangement.spacedBy(5.dp)
                            ) {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .basicMarquee(iterations = Int.MAX_VALUE),
                                    text = workout.name,
                                    color = if (workout.enabled) Color.White.copy(alpha = .87f) else DisabledContentGray,
                                    style = MaterialTheme.typography.bodyLarge,
                                )
                                if (workout.description.isNotEmpty()) {
                                    Text(
                                        modifier = Modifier.fillMaxWidth(),
                                        text = workout.description,
                                        color = if (workout.enabled) Color.White.copy(alpha = .87f) else DisabledContentGray,
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
        }
        
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Button(
                onClick = {
                    appViewModel.setScreenData(
                        ScreenData.NewWorkout(selectedPlanId)
                    )
                }
            ) {
                Icon(
                    imageVector = Icons.Filled.Add,
                    contentDescription = "Add",
                    tint = MaterialTheme.colorScheme.background,
                )
            }
        }
    }
}
