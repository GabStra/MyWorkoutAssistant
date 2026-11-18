package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.text.AnnotatedString
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.presentation.theme.asNumeral
import com.gabstra.myworkoutassistant.presentation.theme.numeralMicro

private val MetadataLineItemHeight = 16.dp

@Composable
fun ExerciseMetadataStrip(
    modifier: Modifier = Modifier,
    exerciseLabel: String? = null,
    supersetExerciseIndex: Int? = null,
    supersetExerciseTotal: Int? = null,
    setLabelPrefix: String? = null,
    setLabel: String? = null,
    repRange: String? = null,
    sideIndicator: String? = null,
    currentSideIndex: UInt? = null,
    onTap: (() -> Unit)? = null,
) {
    val resolvedSetLabelPrefix = setLabelPrefix ?: stringResource(R.string.components_label_set)
    val exerciseLabelText = stringResource(R.string.components_label_exercise)
    val targetLabelText = stringResource(R.string.components_label_target)
    val repsSuffix = stringResource(R.string.components_reps_suffix)
    val leftSideLabel = stringResource(R.string.components_side_left)
    val rightSideLabel = stringResource(R.string.components_side_right)
    val baseStyle = MaterialTheme.typography.bodySmall.copy(
        lineHeight = MaterialTheme.typography.bodySmall.fontSize,
        platformStyle = PlatformTextStyle(includeFontPadding = false),
        lineHeightStyle = LineHeightStyle(
            alignment = LineHeightStyle.Alignment.Center,
            trim = LineHeightStyle.Trim.Both
        )
    )
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
            horizontalArrangement = Arrangement.spacedBy(5.dp, Alignment.CenterHorizontally),
            verticalArrangement = Arrangement.spacedBy(1.dp, Alignment.CenterVertically),
            itemVerticalAlignment = Alignment.CenterVertically
        ) {
            exerciseLabel?.let {
                MetadataLineItem {
                    LabeledNumericValue(
                        label = exerciseLabelText,
                        value = it,
                        style = baseStyle,
                        color = secondaryTextColor,
                    )
                }
            }

            if (supersetExerciseTotal != null && supersetExerciseIndex != null) {
                MetadataLineItem {
                    Text(
                        text = buildAnnotatedString {
                            withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor, fontWeight = FontWeight.Normal)) {
                                fun separator() {
                                    withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor)) {
                                        append(" / ")
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
                        style = baseStyle,
                        maxLines = 1,
                        softWrap = false
                    )
                }
            }

            setLabel?.let {
                MetadataLineItem {
                    LabeledNumericValue(
                        label = "$resolvedSetLabelPrefix:",
                        value = it,
                        style = baseStyle,
                        color = secondaryTextColor,
                    )
                }
            }

            repRange?.let {
                MetadataLineItem {
                    LabeledNumericValue(
                        label = targetLabelText,
                        value = it,
                        style = baseStyle,
                        color = secondaryTextColor,
                        suffix = repsSuffix,
                    )
                }
            }

            sideIndicator?.let {
                val side1Color = if (currentSideIndex == 1u) primaryColor else surfaceContainerHigh
                val side2Color = if (currentSideIndex == 2u) primaryColor else surfaceContainerHigh
                MetadataLineItem {
                    Text(
                        text = buildAnnotatedString {
                            withStyle(baseStyle.toSpanStyle().copy(color = side1Color, fontWeight = FontWeight.Bold)) {
                                append(leftSideLabel)
                            }
                            withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor)) {
                                append(" / ")
                            }
                            withStyle(baseStyle.toSpanStyle().copy(color = side2Color, fontWeight = FontWeight.Bold)) {
                                append(rightSideLabel)
                            }
                        },
                        style = baseStyle,
                        maxLines = 1,
                        softWrap = false
                    )
                }
            }
        }
    }
}

@Composable
private fun MetadataLineItem(content: @Composable () -> Unit) {
    Box(
        modifier = Modifier.heightIn(min = MetadataLineItemHeight),
        contentAlignment = Alignment.Center
    ) {
        content()
    }
}
