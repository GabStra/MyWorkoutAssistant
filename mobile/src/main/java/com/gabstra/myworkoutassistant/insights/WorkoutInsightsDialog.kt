package com.gabstra.myworkoutassistant.insights

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ContentSubtitle
import com.gabstra.myworkoutassistant.composables.ContentTitle
import com.gabstra.myworkoutassistant.composables.SecondarySurface
import com.gabstra.myworkoutassistant.composables.StandardDialog

sealed class WorkoutInsightsUiState {
    data object Idle : WorkoutInsightsUiState()
    data object PreparingModel : WorkoutInsightsUiState()
    data class Generating(val partialText: String = "") : WorkoutInsightsUiState()
    data class Success(val title: String, val text: String) : WorkoutInsightsUiState()
    data class Error(val message: String) : WorkoutInsightsUiState()
}

@Composable
fun WorkoutInsightsDialog(
    show: Boolean,
    title: String,
    state: WorkoutInsightsUiState,
    isModelConfigured: Boolean,
    onDismiss: () -> Unit,
    onImportModel: () -> Unit,
    onGenerate: () -> Unit,
    onClearModel: () -> Unit,
) {
    if (!show) return

    LaunchedEffect(show, isModelConfigured, state) {
        if (show && isModelConfigured && state is WorkoutInsightsUiState.Idle) {
            onGenerate()
        }
    }

    StandardDialog(
        onDismissRequest = onDismiss,
        title = title,
        body = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 120.dp, max = 420.dp),
                verticalArrangement = Arrangement.spacedBy(Spacing.md),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                when {
                    !isModelConfigured -> {
                        SecondarySurface {
                            Text(
                                text = "No LiteRT-LM model is configured. Import a local .litertlm model file to enable on-device insights.",
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.padding(Spacing.md)
                            )
                        }
                    }

                    state is WorkoutInsightsUiState.PreparingModel -> {
                        CenteredInsightBodySurface {
                            LoadingText("Preparing local model...")
                        }
                    }

                    state is WorkoutInsightsUiState.Generating -> {
                        CenteredInsightBodySurface {
                            LoadingText("Generating local insights...")
                        }
                    }

                    state is WorkoutInsightsUiState.Success -> {
                        InsightBodySurface {
                            WorkoutInsightMarkdown(
                                markdown = state.text,
                            )
                        }
                    }

                    state is WorkoutInsightsUiState.Error -> {
                        SecondarySurface(
                            backgroundColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.55f)
                        ) {
                            Text(
                                text = state.message,
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.padding(Spacing.md)
                            )
                        }
                    }

                    else -> {
                        SecondarySurface {
                            Text(
                                text = "Generate concise insights from your local workout history using the selected LiteRT-LM model.",
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.padding(Spacing.md)
                            )
                        }
                    }
                }
            }
        },
        confirmText = if (isModelConfigured) null else "Import model",
        onConfirm = if (isModelConfigured) null else onImportModel,
        dismissText = "Close",
        onDismissButton = onDismiss,
        showConfirm = !isModelConfigured
    )
}

@Composable
private fun InsightStatusHeader(
    state: WorkoutInsightsUiState,
    isModelConfigured: Boolean,
) {
    val statusLabel = when {
        !isModelConfigured -> "Model required"
        state is WorkoutInsightsUiState.PreparingModel -> "Preparing"
        state is WorkoutInsightsUiState.Generating -> "Generating"
        state is WorkoutInsightsUiState.Success -> "Ready"
        state is WorkoutInsightsUiState.Error -> "Needs retry"
        else -> "Local model"
    }
    val supportingText = when {
        !isModelConfigured -> "Import a LiteRT-LM file to enable on-device insights."
        state is WorkoutInsightsUiState.Success -> "Structured feedback from your recent workout data."
        state is WorkoutInsightsUiState.Error -> "The local model could not complete this insight request."
        else -> "On-device analysis using your selected LiteRT-LM model."
    }

    SecondarySurface {
        Column(
            modifier = Modifier.padding(horizontal = Spacing.md, vertical = Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                ContentTitle(text = "Workout Insights")
                Text(
                    text = statusLabel,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .background(
                            color = MaterialTheme.colorScheme.background,
                            shape = RoundedCornerShape(999.dp)
                        )
                        .padding(horizontal = Spacing.sm, vertical = Spacing.xs)
                )
            }
            ContentSubtitle(text = supportingText)
        }
    }
}

@Composable
private fun LoadingText(label: String) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.md)
    ) {
        CircularProgressIndicator(
            strokeWidth = 2.dp,
            modifier = Modifier.size(25.dp),
            color = MaterialTheme.colorScheme.primary,
        )
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium
        )
    }
}

@Composable
private fun InsightBodySurface(
    content: @Composable ColumnScope.() -> Unit,
) {
    val scrollState = rememberScrollState()
    SecondarySurface {
        Column(
            modifier = Modifier
                .heightIn(max = 260.dp)
                .verticalScroll(scrollState)
                .padding(Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
            content = content
        )
    }
}

@Composable
private fun CenteredInsightBodySurface(
    content: @Composable () -> Unit,
) {
    SecondarySurface {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 100.dp)
                .padding(Spacing.md),
            contentAlignment = Alignment.Center
        ) {
            content()
        }
    }
}
