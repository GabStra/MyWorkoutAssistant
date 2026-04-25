package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

@Composable
fun ExerciseMetadataStrip(
    modifier: Modifier = Modifier,
    exerciseLabel: String? = null,
    supersetExerciseIndex: Int? = null,
    supersetExerciseTotal: Int? = null,
    setLabel: String? = null,
    repRange: String? = null,
    sideIndicator: String? = null,
    currentSideIndex: UInt? = null,
    onTap: (() -> Unit)? = null,
) {
    val baseStyle = MaterialTheme.typography.bodySmall
    val primaryColor = MaterialTheme.colorScheme.primary
    val surfaceContainerHigh = MaterialTheme.colorScheme.surfaceContainerHigh
    val secondaryTextColor = MaterialTheme.colorScheme.onSurfaceVariant
    val clickableModifier = if (onTap != null) {
        modifier.clickable(onClick = onTap)
    } else {
        modifier
    }

    if (
        exerciseLabel != null ||
        (supersetExerciseTotal != null && supersetExerciseIndex != null) ||
        setLabel != null ||
        repRange != null ||
        sideIndicator != null
    ) {
        FlowRow(
            modifier = clickableModifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            exerciseLabel?.let {
                Text(
                    text = "Exercise: $it",
                    style = baseStyle,
                    color = secondaryTextColor
                )
            }

            if (supersetExerciseTotal != null && supersetExerciseIndex != null) {
                Text(
                    text = buildAnnotatedString {
                        withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor, fontWeight = FontWeight.Normal)) {
                            fun separator() {
                                withStyle(baseStyle.toSpanStyle().copy(baselineShift = BaselineShift(0.25f))) {
                                    append("↔")
                                }
                            }

                            (0 until supersetExerciseTotal).forEach { i ->
                                if (i > 0) separator()
                                withStyle(
                                    SpanStyle(
                                        color = if (i == supersetExerciseIndex) primaryColor else surfaceContainerHigh,
                                        fontWeight = FontWeight.Bold
                                    )
                                ) {
                                    append(('A' + i).toString())
                                }
                            }
                        }
                    },
                    style = baseStyle
                )
            }

            setLabel?.let {
                Text(
                    text = "Set: $it",
                    style = baseStyle,
                    color = secondaryTextColor
                )
            }

            repRange?.let {
                Text(
                    text = "Reps: $it",
                    style = baseStyle,
                    color = secondaryTextColor
                )
            }

            sideIndicator?.let {
                val side1Color = if (currentSideIndex == 1u) primaryColor else surfaceContainerHigh
                val side2Color = if (currentSideIndex == 2u) primaryColor else surfaceContainerHigh
                Text(
                    text = buildAnnotatedString {
                        withStyle(SpanStyle(color = side1Color, fontWeight = FontWeight.Bold)) {
                            append("L")
                        }
                        withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor, baselineShift = BaselineShift(0.25f))) {
                            append("↔")
                        }
                        withStyle(SpanStyle(color = side2Color, fontWeight = FontWeight.Bold)) {
                            append("R")
                        }
                    },
                    style = baseStyle
                )
            }
        }
    }
}
