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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold
import com.gabstra.myworkoutassistant.composables.EditPlanNameDialog
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlansScreen(appViewModel: AppViewModel) {
    val context = LocalContext.current
    val plans by appViewModel.workoutPlansFlow.collectAsState()
    var planToEditId by remember { mutableStateOf<UUID?>(null) }
    var editPlanError by remember { mutableStateOf<String?>(null) }
    val planSaveError = stringResource(R.string.loc_plan_error_save)
    val planToEdit = planToEditId?.let { planId -> plans.firstOrNull { it.id == planId } }

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
                        text = stringResource(R.string.loc_plans),
                        textAlign = TextAlign.Center,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = {
                        if (!appViewModel.goBack()) {
                            appViewModel.setScreenData(com.gabstra.myworkoutassistant.ScreenData.Workouts(1))
                        }
                    }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.common_back))
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
                text = stringResource(R.string.loc_scr_plans_hint),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (plans.isEmpty()) {
                Text(
                    text = stringResource(R.string.loc_scr_no_plans),
                    modifier = Modifier.padding(vertical = Spacing.md),
                    style = MaterialTheme.typography.bodyLarge,
                )
            } else {
                plans.forEach { plan ->
                    val editPlanDescription = stringResource(R.string.loc_scr_edit_plan_cd, plan.name)
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
                                    .semantics { contentDescription = editPlanDescription },
                                onClick = {
                                    editPlanError = null
                                    planToEditId = plan.id
                                },
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
            errorMessage = editPlanError,
            onDismiss = {
                planToEditId = null
                editPlanError = null
            },
            onConfirm = { newName, suggestNextPrescription ->
                val saved = appViewModel.updateWorkoutPlanSettings(
                    planId = plan.id,
                    newName = newName,
                    suggestNextPrescription = suggestNextPrescription,
                )
                if (saved) {
                    appViewModel.scheduleWorkoutSave(context)
                    planToEditId = null
                    editPlanError = null
                } else {
                    editPlanError = planSaveError
                }
            },
        )
    }
}
