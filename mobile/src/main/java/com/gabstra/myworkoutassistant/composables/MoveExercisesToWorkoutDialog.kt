package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.shared.UNASSIGNED_PLAN_NAME
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import java.util.UUID

@Composable
fun MoveExercisesToWorkoutDialog(
    show: Boolean,
    onDismiss: () -> Unit,
    workouts: List<Workout>,
    workoutPlans: List<WorkoutPlan>,
    currentWorkout: Workout,
    onMove: (Workout) -> Unit
) {
    if (show) {
        StandardDialog(
            onDismissRequest = onDismiss,
            title = "Move exercises",
            body = {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md)
                ) {
                    val targetWorkouts = workouts
                        .filter { it.enabled && it.isActive && it.id != currentWorkout.id }

                    if (targetWorkouts.isEmpty()) {
                        MoveTargetEmptyState()
                    } else {
                        Text(
                            text = "Tap a workout below to move your selected exercises into it.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.fillMaxWidth()
                        )

                        val shownIds = mutableSetOf<UUID>()
                        var isFirstSection = true

                        workoutPlans.forEach { plan ->
                            val inPlan = targetWorkouts
                                .filter { it.workoutPlanId == plan.id }
                                .sortedBy { it.order }
                            if (inPlan.isEmpty()) return@forEach

                            MoveTargetPlanSection(
                                title = plan.name,
                                isFirstSection = isFirstSection,
                                workouts = inPlan,
                                onMove = onMove,
                                onDismiss = onDismiss,
                            )
                            inPlan.forEach { shownIds.add(it.id) }
                            isFirstSection = false
                        }

                        val remaining = targetWorkouts
                            .filter { it.id !in shownIds }
                            .sortedBy { it.order }
                        if (remaining.isNotEmpty()) {
                            val orphanTitle = when {
                                remaining.all { it.workoutPlanId == null } ->
                                    UNASSIGNED_PLAN_NAME
                                else -> "Other workouts"
                            }
                            if (!isFirstSection) {
                                HorizontalDivider(
                                    modifier = Modifier.padding(vertical = Spacing.xs),
                                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)
                                )
                            }
                            MoveTargetPlanSection(
                                title = orphanTitle,
                                isFirstSection = isFirstSection,
                                workouts = remaining,
                                onMove = onMove,
                                onDismiss = onDismiss,
                            )
                        }
                    }
                }
            },
            showConfirm = false,
            dismissText = "Close",
            onDismissButton = onDismiss
        )
    }
}

@Composable
private fun MoveTargetEmptyState() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = Spacing.lg),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Spacing.md)
    ) {
        Icon(
            imageVector = Icons.Outlined.FitnessCenter,
            contentDescription = null,
            modifier = Modifier.size(40.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
        )
        Text(
            text = "No destination yet",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface
        )
        Text(
            text = "Add another workout or turn one on, then open this again.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = Spacing.sm)
        )
    }
}

@Composable
private fun MoveTargetPlanSection(
    title: String,
    isFirstSection: Boolean,
    workouts: List<Workout>,
    onMove: (Workout) -> Unit,
    onDismiss: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(Spacing.sm)
    ) {
        MoveTargetPlanHeader(title = title, isFirst = isFirstSection)
        workouts.forEach { w ->
            MoveTargetWorkoutRow(
                workout = w,
                onMove = onMove,
                onDismiss = onDismiss
            )
        }
    }
}

@Composable
private fun MoveTargetPlanHeader(
    title: String,
    isFirst: Boolean,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = if (isFirst) 0.dp else Spacing.sm),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun MoveTargetWorkoutRow(
    workout: Workout,
    onMove: (Workout) -> Unit,
    onDismiss: () -> Unit,
) {
    val moveLabel = "Move to ${workout.name}"
    OutlinedCard(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(
                onClickLabel = moveLabel,
                onClick = {
                    onMove(workout)
                    onDismiss()
                }
            ),
        shape = MaterialTheme.shapes.medium
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.md, vertical = Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
        ) {
            Text(
                text = workout.name,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f)
            )
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.outline,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}
