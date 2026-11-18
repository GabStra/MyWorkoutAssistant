package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import java.util.UUID

@Composable
fun MoveWorkoutDialog(
    show: Boolean,
    workoutName: String,
    workoutCount: Int = 1,
    availablePlans: List<WorkoutPlan>,
    errorMessage: String? = null,
    onDismiss: () -> Unit,
    onMoveToPlan: (UUID?) -> Unit,
    onCreateNewPlan: () -> Unit
) {
    if (show) {
        StandardDialog(
            onDismissRequest = onDismiss,
            title = if (workoutCount > 1) {
                stringResource(R.string.loc_move_workouts, workoutCount)
            } else {
                stringResource(R.string.loc_move_named, workoutName)
            },
            body = {
                Text(
                    text = stringResource(R.string.loc_select_workout_plan),
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(bottom = Spacing.md)
                )

                if (errorMessage != null) {
                    Text(
                        text = errorMessage,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(bottom = Spacing.sm)
                    )
                }

                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    availablePlans.forEach { plan ->
                        OutlinedCard(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    onMoveToPlan(plan.id)
                                }
                        ) {
                            Text(
                                text = plan.name,
                                modifier = Modifier.padding(Spacing.md),
                                style = MaterialTheme.typography.bodyLarge
                            )
                        }
                    }

                    OutlinedCard(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                onMoveToPlan(null)
                            }
                    ) {
                        Text(
                            text = stringResource(R.string.loc_no_plan),
                            modifier = Modifier.padding(Spacing.md),
                            style = MaterialTheme.typography.bodyLarge
                        )
                    }

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
                            text = stringResource(R.string.loc_create_new_plan),
                            modifier = Modifier.padding(Spacing.md),
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onPrimaryContainer
                        )
                    }
                }
            },
            showConfirm = false,
            dismissText = stringResource(R.string.common_cancel),
            onDismissButton = onDismiss
        )
    }
}
