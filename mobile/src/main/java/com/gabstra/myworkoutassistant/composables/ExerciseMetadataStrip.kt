package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import com.gabstra.myworkoutassistant.Spacing

@Composable
fun ExerciseMetadataStrip(
    modifier: Modifier = Modifier,
    exerciseLabel: String? = null,
    supersetExerciseLabel: String? = null,
    supersetExerciseIndex: Int? = null,
    supersetExerciseTotal: Int? = null,
    setLabel: String? = null,
    repRange: String? = null,
    sideIndicator: String? = null,
    currentSideIndex: UInt? = null,
    isUnilateral: Boolean = false,
    equipmentName: String? = null,
    accessoryNames: String? = null,
    accessoryNameList: List<String> = emptyList(),
    textColor: Color = MaterialTheme.colorScheme.onBackground,
    onTap: (() -> Unit)? = null,
) {
    var marqueeEnabled by remember { mutableStateOf(false) }

    val exerciseIndicatorString = remember(supersetExerciseIndex, supersetExerciseTotal) {
        if (supersetExerciseIndex != null && supersetExerciseTotal != null && supersetExerciseTotal > 0) {
            (0 until supersetExerciseTotal).map { ('A' + it).toString() }.joinToString(" ↔ ")
        } else {
            null
        }
    }

    val metadataParts = remember(
        exerciseLabel,
        supersetExerciseLabel,
        exerciseIndicatorString,
        setLabel,
        repRange,
        sideIndicator,
        isUnilateral,
    ) {
        buildList {
            exerciseLabel?.takeIf { it.isNotBlank() }?.let { add(it) }
            supersetExerciseLabel?.takeIf { it.isNotBlank() }?.let { add(it) }
            exerciseIndicatorString?.takeIf { it.isNotBlank() }?.let { add(it) }
            setLabel?.takeIf { it.isNotBlank() }?.let { add(it) }
            repRange?.takeIf { it.isNotBlank() }?.let { add("Target: $it reps") }
            sideIndicator?.takeIf { it.isNotBlank() }?.let { add(it) }
            if (isUnilateral) add("Unilateral")
        }
    }

    val metadataText = remember(metadataParts) {
        buildString {
            metadataParts.forEachIndexed { index, part ->
                if (index > 0) append(" | ")
                append(part)
            }
        }
    }

    val primaryColor = MaterialTheme.colorScheme.primary
    val needsHighlighting =
        (sideIndicator != null && currentSideIndex != null && sideIndicator.contains("↔") && metadataText.contains(sideIndicator)) ||
            (exerciseIndicatorString != null && supersetExerciseIndex != null && metadataText.contains(exerciseIndicatorString))

    val annotatedText = remember(
        metadataText,
        sideIndicator,
        currentSideIndex,
        exerciseIndicatorString,
        supersetExerciseIndex,
        primaryColor,
        textColor
    ) {
        if (needsHighlighting) {
            buildAnnotatedString {
                val parts = metadataText.split(" | ")
                parts.forEachIndexed { index, part ->
                    if (index > 0) append(" | ")
                    when {
                        part == sideIndicator -> {
                            val sideParts = part.split(" ↔ ")
                            if (sideParts.size == 2) {
                                val (sideA, sideB) = sideParts
                                withStyle(
                                    SpanStyle(
                                        color = if (currentSideIndex == 1u) primaryColor else textColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                ) {
                                    append(sideA)
                                }
                                append(" ↔ ")
                                withStyle(
                                    SpanStyle(
                                        color = if (currentSideIndex == 2u) primaryColor else textColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                ) {
                                    append(sideB)
                                }
                            } else {
                                append(part)
                            }
                        }

                        part == exerciseIndicatorString && supersetExerciseIndex != null -> {
                            val exerciseParts = part.split(" ↔ ")
                            exerciseParts.forEachIndexed { i, segment ->
                                if (i > 0) append(" ↔ ")
                                withStyle(
                                    SpanStyle(
                                        color = if (i == supersetExerciseIndex) primaryColor else textColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                ) {
                                    append(segment)
                                }
                            }
                        }

                        else -> append(part)
                    }
                }
            }
        } else {
            AnnotatedString(metadataText)
        }
    }

    val resolvedAccessoryNames = remember(accessoryNames, accessoryNameList) {
        accessoryNameList.ifEmpty {
            accessoryNames
                ?.split(",")
                ?.map { it.trim() }
                ?.filter { it.isNotBlank() }
                .orEmpty()
        }
    }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(Spacing.xs)
    ) {
        if (metadataText.isNotEmpty()) {
            FadingText(
                text = annotatedText,
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.bodySmall,
                color = textColor,
                marqueeEnabled = marqueeEnabled,
                onClick = {
                    marqueeEnabled = !marqueeEnabled
                    onTap?.invoke()
                }
            )
        }

        EquipmentAccessoryMetadata(
            equipmentName = equipmentName,
            accessoryNames = resolvedAccessoryNames,
        )
    }
}

@Composable
fun EquipmentAccessoryMetadata(
    equipmentName: String?,
    accessoryNames: List<String>,
    modifier: Modifier = Modifier,
    horizontalAlignment: Alignment.Horizontal = Alignment.CenterHorizontally,
    textAlign: TextAlign = TextAlign.Center,
) {
    val equipment = equipmentName?.takeIf { it.isNotBlank() }
    val accessories = accessoryNames.filter { it.isNotBlank() }

    if (equipment == null && accessories.isEmpty()) return

    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = horizontalAlignment,
        verticalArrangement = Arrangement.spacedBy(Spacing.xs),
    ) {
        if (equipment != null) {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = buildAnnotatedString {
                    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) {
                        append("Equipment: ")
                    }
                    append(equipment)
                },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                textAlign = textAlign,
            )
        }
        if (accessories.isNotEmpty()) {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = buildAnnotatedString {
                    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) {
                        append("Accessories: ")
                    }
                    append(accessories.joinToString(" · "))
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = textAlign,
            )
        }
    }
}
