package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
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
        StandardDialog(
            onDismissRequest = onDismiss,
            title = if (workoutCount > 1) {
                "Move $workoutCount workouts"
            } else {
                "Move \"$workoutName\""
            },
            body = {
                Text(
                    text = "Select a workout plan:",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(bottom = Spacing.md)
                )
                
                // Filter out current plan and deduplicate
                val filteredPlans = remember(currentPlanId, availablePlans) {
                    availablePlans
                        .filter { plan -> plan.id != currentPlanId }
                        .distinctBy { it.id }
                }
                
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
                    
                    // List of plans (filtered and deduplicated)
                    items(filteredPlans) { plan ->
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
                    
                    // Create New Plan option (at the bottom with primary color)
                    item {
                        OutlinedCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(MaterialTheme.colorScheme.primaryContainer)
                                .clickable {
                                    onCreateNewPlan()
                                },
                            border = BorderStroke(2.dp, MaterialTheme.colorScheme.primary)
                        ) {
                            Text(
                                text = "+ Create New Plan",
                                modifier = Modifier.padding(Spacing.md),
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onPrimaryContainer
                            )
                        }
                    }
                }
            },
            showConfirm = false,
            dismissText = "Cancel",
            onDismissButton = onDismiss
        )
    }
}

