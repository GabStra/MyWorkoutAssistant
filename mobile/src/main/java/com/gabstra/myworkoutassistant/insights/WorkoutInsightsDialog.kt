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
import androidx.compose.foundation.shape.RoundedCornerShape
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
    data object ImportingModel : WorkoutInsightsUiState()
    data object PreparingModel : WorkoutInsightsUiState()
    data class Generating(
        val partialText: String = "",
        val phase: WorkoutInsightsPhase = WorkoutInsightsPhase.FINAL_SYNTHESIS,
        val statusText: String = "",
    ) : WorkoutInsightsUiState()
    data class Success(val title: String, val text: String) : WorkoutInsightsUiState()
    data class Error(
        val message: String,
    ) : WorkoutInsightsUiState()
}

@Composable
fun WorkoutInsightsDialog(
    show: Boolean,
    title: String,
    state: WorkoutInsightsUiState,
    configurationState: WorkoutInsightsConfigurationState,
    onDismiss: () -> Unit,
    onConfigure: (() -> Unit)?,
    onGenerate: () -> Unit,
) {
    if (!show) return

    LaunchedEffect(show, configurationState.isConfigured, state, configurationState.mode) {
        if (show && configurationState.isConfigured && state is WorkoutInsightsUiState.Idle) {
            onGenerate()
        }
    }

    StandardDialog(
        onDismissRequest = onDismiss,
        title = title,
        body = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(Spacing.md),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                when {
                    state is WorkoutInsightsUiState.ImportingModel -> {
                        CenteredInsightBody {
                            LoadingText("Importing local model...")
                        }
                    }

                    !configurationState.isConfigured -> {
                        Text(
                            text = configurationState.missingConfigurationMessage,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }

                    state is WorkoutInsightsUiState.PreparingModel -> {
                        CenteredInsightBody {
                            LoadingText(
                                when (configurationState.mode) {
                                    WorkoutInsightsMode.LOCAL -> "Preparing local request..."
                                    WorkoutInsightsMode.REMOTE -> "Preparing remote request..."
                                }
                            )
                        }
                    }

                    state is WorkoutInsightsUiState.Generating -> {
                        val statusLabel = state.statusText.ifBlank {
                            defaultProgressLabel(state.phase)
                        }
                        // Streaming reveal: `partialText` already holds only settled markdown
                        // blocks (see settledMarkdownPrefix), so it renders without ever
                        // showing a half-written line. Until the first block completes (and
                        // during tool phases) only the status row is shown.
                        if (state.partialText.isBlank()) {
                            CenteredInsightBody {
                                LoadingText(label = statusLabel)
                            }
                        } else {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .heightIn(min = 200.dp),
                                verticalArrangement = Arrangement.spacedBy(Spacing.md)
                            ) {
                                WorkoutInsightMarkdown(markdown = state.partialText)
                                GeneratingStatusRow(statusLabel)
                            }
                        }
                    }

                    state is WorkoutInsightsUiState.Success -> {
                        WorkoutInsightMarkdown(
                            markdown = state.text,
                        )
                    }

                    state is WorkoutInsightsUiState.Error -> {
                        Text(
                            text = state.message,
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }

                    else -> {
                        Text(
                            text = when (configurationState.mode) {
                                WorkoutInsightsMode.LOCAL ->
                                    "Generate concise insights from your workout history using the selected local LiteRT-LM model."
                                WorkoutInsightsMode.REMOTE ->
                                    "Generate concise insights from your workout history using the configured hosted OpenAI-compatible API."
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }
            }
        },
        confirmText = if (configurationState.isConfigured || state is WorkoutInsightsUiState.ImportingModel) null else configurationState.configureActionLabel,
        onConfirm = if (configurationState.isConfigured || state is WorkoutInsightsUiState.ImportingModel) null else onConfigure,
        dismissText = "Close",
        onDismissButton = onDismiss,
        showConfirm = !configurationState.isConfigured &&
            state !is WorkoutInsightsUiState.ImportingModel &&
            onConfigure != null &&
            configurationState.configureActionLabel != null
    )
}

@Composable
private fun InsightStatusHeader(
    state: WorkoutInsightsUiState,
    isModelConfigured: Boolean,
) {
    val statusLabel = when {
        !isModelConfigured -> "Model required"
        state is WorkoutInsightsUiState.ImportingModel -> "Importing"
        state is WorkoutInsightsUiState.PreparingModel -> "Preparing"
        state is WorkoutInsightsUiState.Generating -> "Generating"
        state is WorkoutInsightsUiState.Success -> "Ready"
        state is WorkoutInsightsUiState.Error -> "Needs retry"
        else -> "Local model"
    }
    val supportingText = when {
        state is WorkoutInsightsUiState.ImportingModel -> "Copying the selected LiteRT-LM model before generating insights."
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
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Spacing.md)
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

/** Compact inline progress row shown under the streamed markdown blocks while generating. */
@Composable
private fun GeneratingStatusRow(label: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
    ) {
        CircularProgressIndicator(
            strokeWidth = 2.dp,
            modifier = Modifier.size(16.dp),
            color = MaterialTheme.colorScheme.primary,
        )
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

private fun defaultProgressLabel(
    phase: WorkoutInsightsPhase,
): String = when (phase) {
    WorkoutInsightsPhase.PREPARING_TOOLS -> "Loading insight model..."
    WorkoutInsightsPhase.FETCHING_CONTEXT -> "Fetching workout context..."
    WorkoutInsightsPhase.SUMMARIZING_CONTEXT -> "Summarizing relevant history..."
    WorkoutInsightsPhase.CHART_ANALYSIS -> "Analyzing heart-rate chart..."
    WorkoutInsightsPhase.FINAL_SYNTHESIS -> "Generating insight..."
}

@Composable
private fun CenteredInsightBody(
    content: @Composable () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 200.dp),
        contentAlignment = Alignment.Center
    ) {
        content()
    }
}
