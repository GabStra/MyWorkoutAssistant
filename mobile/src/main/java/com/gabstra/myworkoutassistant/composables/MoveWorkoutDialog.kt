package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import java.util.UUID

@Composable
fun MoveWorkoutDialog(
    show: Boolean,
    workoutName: String,
    workoutCount: Int = 1,
    currentPlanId: UUID?,
    availablePlans: List<WorkoutPlan>,
    onDismiss: () -> Unit,
    onMoveToPlan: (UUID?) -> Unit,
    onCreateNewPlan: () -> Unit
) {
    if (show) {
        Dialog(onDismissRequest = onDismiss) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(Spacing.lg),
                verticalArrangement = Arrangement.spacedBy(Spacing.md)
            ) {
                Text(
                    text = if (workoutCount > 1) {
                        "Move $workoutCount workouts"
                    } else {
                        "Move \"$workoutName\""
                    },
                    style = MaterialTheme.typography.titleLarge
                )
                
                Text(
                    text = "Select a workout plan:",
                    style = MaterialTheme.typography.bodyMedium
                )
                
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(300.dp),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    // Option for Unassigned
                    item {
                        OutlinedCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    onMoveToPlan(null)
                                    onDismiss()
                                }
                        ) {
                            Text(
                                text = "Unassigned",
                                modifier = Modifier.padding(Spacing.md),
                                style = MaterialTheme.typography.bodyLarge
                            )
                        }
                    }
                    
                    // Create New Plan option
                    item {
                        OutlinedCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    onCreateNewPlan()
                                }
                        ) {
                            Text(
                                text = "+ Create New Plan",
                                modifier = Modifier.padding(Spacing.md),
                                style = MaterialTheme.typography.bodyLarge
                            )
                        }
                    }
                    
                    // List of plans (deduplicated by ID)
                    items(availablePlans.distinctBy { it.id }) { plan ->
                        OutlinedCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    onMoveToPlan(plan.id)
                                    onDismiss()
                                }
                        ) {
                            Text(
                                text = plan.name,
                                modifier = Modifier.padding(Spacing.md),
                                style = MaterialTheme.typography.bodyLarge
                            )
                        }
                    }
                }
                
                Spacer(modifier = Modifier.height(Spacing.sm))
                
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End
                ) {
                    TextButton(onClick = onDismiss) {
                        Text("Cancel")
                    }
                }
            }
        }
    }
}

