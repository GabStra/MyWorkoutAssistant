package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle

@Composable
fun ExerciseMetadataStrip(
    modifier: Modifier = Modifier,
    exerciseLabel: String? = null,
    supersetExerciseLabel: String? = null,
    supersetExerciseIndex: Int? = null,
    supersetExerciseTotal: Int? = null,
    setLabel: String? = null,
    sideIndicator: String? = null,
    currentSideIndex: UInt? = null,
    isUnilateral: Boolean = false,
    equipmentName: String? = null,
    accessoryNames: String? = null,
    textColor: Color = MaterialTheme.colorScheme.onBackground,
    onTap: (() -> Unit)? = null,
) {
    var marqueeEnabled by remember { mutableStateOf(false) }

    val exerciseIndicatorString = remember(supersetExerciseIndex, supersetExerciseTotal) {
        if (supersetExerciseIndex != null && supersetExerciseTotal != null && supersetExerciseTotal > 0) {
            (0 until supersetExerciseTotal).map { ('A' + it).toString() }.joinToString(" ↔ ")
        } else null
    }

    val metadataParts = remember(
        exerciseLabel,
        supersetExerciseLabel,
        exerciseIndicatorString,
        setLabel,
        sideIndicator,
        isUnilateral,
        equipmentName,
        accessoryNames
    ) {
        buildList {
            exerciseLabel?.takeIf { it.isNotBlank() }?.let { add(it) }
            supersetExerciseLabel?.takeIf { it.isNotBlank() }?.let { add(it) }
            exerciseIndicatorString?.takeIf { it.isNotBlank() }?.let { add(it) }
            setLabel?.takeIf { it.isNotBlank() }?.let { add(it) }
            sideIndicator?.takeIf { it.isNotBlank() }?.let { add(it) }
            if (isUnilateral) add("Unilateral")
            equipmentName?.takeIf { it.isNotBlank() }?.let { add("Equipment: $it") }
            accessoryNames?.takeIf { it.isNotBlank() }?.let { add("Accessory: $it") }
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

    val needsHighlighting = (sideIndicator != null && currentSideIndex != null && sideIndicator.contains("↔") && metadataText.contains(sideIndicator)) ||
        (exerciseIndicatorString != null && supersetExerciseIndex != null && metadataText.contains(exerciseIndicatorString))

    // Build annotated string for side indicator and exercise indicator highlighting
    val annotatedText = remember(metadataText, sideIndicator, currentSideIndex, exerciseIndicatorString, supersetExerciseIndex, primaryColor, textColor) {
        if (needsHighlighting) {
            buildAnnotatedString {
                val parts = metadataText.split(" | ")
                parts.forEachIndexed { index, part ->
                    if (index > 0) {
                        append(" | ")
                    }
                    when {
                        part == sideIndicator -> {
                            // Highlight current side in side indicator (① ↔ ②)
                            val sideParts = part.split(" ↔ ")
                            if (sideParts.size == 2) {
                                val (sideA, sideB) = sideParts
                                withStyle(
                                    style = SpanStyle(
                                        color = if (currentSideIndex == 1u) primaryColor else textColor,
                                        fontWeight = FontWeight.Bold
                                    )
                                ) {
                                    append(sideA)
                                }
                                append(" ↔ ")
                                withStyle(
                                    style = SpanStyle(
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
                            // Highlight current exercise in superset indicator (A ↔ B or A ↔ B ↔ C)
                            val idx = supersetExerciseIndex
                            val exerciseParts = part.split(" ↔ ")
                            exerciseParts.forEachIndexed { i, segment ->
                                if (i > 0) append(" ↔ ")
                                withStyle(
                                    style = SpanStyle(
                                        color = if (i == idx) primaryColor else textColor,
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
    
    if (metadataText.isNotEmpty()) {
        FadingText(
            text = annotatedText,
            modifier = modifier.fillMaxWidth(),
            style = MaterialTheme.typography.bodySmall,
            color = textColor,
            marqueeEnabled = marqueeEnabled,
            onClick = {
                marqueeEnabled = !marqueeEnabled
                onTap?.invoke()
            }
        )
    }
}
