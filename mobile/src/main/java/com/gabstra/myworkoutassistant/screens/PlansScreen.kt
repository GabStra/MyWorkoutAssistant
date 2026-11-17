package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold
import com.gabstra.myworkoutassistant.composables.EditPlanNameDialog
import com.gabstra.myworkoutassistant.shared.WorkoutPlan

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlansScreen(appViewModel: AppViewModel) {
    val context = LocalContext.current
    val plans by appViewModel.workoutPlansFlow.collectAsState()
    var planToEdit by remember { mutableStateOf<WorkoutPlan?>(null) }

    BreadcrumbScaffold(
        topBar = {
            androidx.compose.material3.TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    titleContentColor = MaterialTheme.colorScheme.onBackground,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground,
                ),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = "Plans",
                        textAlign = TextAlign.Center,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = {
                        if (!appViewModel.goBack()) {
                            appViewModel.setScreenData(com.gabstra.myworkoutassistant.ScreenData.Workouts(1))
                        }
                    }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    Spacer(modifier = Modifier.width(48.dp))
                },
            )
        },
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .verticalScroll(rememberScrollState())
                .padding(Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            Text(
                text = "Choose a plan to edit its name and recurring-session guidance setting.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (plans.isEmpty()) {
                Text(
                    text = "No workout plans are available yet.",
                    modifier = Modifier.padding(vertical = Spacing.md),
                    style = MaterialTheme.typography.bodyLarge,
                )
            } else {
                plans.forEach { plan ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
                        ),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(start = Spacing.md, end = Spacing.xs, top = Spacing.xs, bottom = Spacing.xs),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = plan.name,
                                modifier = Modifier.weight(1f),
                                style = MaterialTheme.typography.titleMedium,
                            )
                            Spacer(Modifier.width(Spacing.xs))
                            IconButton(
                                modifier = Modifier
                                    .testTag("edit_plan_${plan.id}")
                                    .semantics { contentDescription = "Edit plan: ${plan.name}" },
                                onClick = { planToEdit = plan },
                            ) {
                                Icon(Icons.Default.Edit, contentDescription = null)
                            }
                        }
                    }
                }
            }
        }
    }

    planToEdit?.let { plan ->
        EditPlanNameDialog(
            show = true,
            currentName = plan.name,
            suggestNextPrescription = plan.suggestNextPrescription,
            onDismiss = { planToEdit = null },
            onConfirm = { newName, suggestNextPrescription ->
                appViewModel.updateWorkoutPlan(
                    plan.copy(
                        name = newName,
                        suggestNextPrescription = suggestNextPrescription,
                    ),
                )
                appViewModel.scheduleWorkoutSave(context)
                planToEdit = null
            },
        )
    }
}
