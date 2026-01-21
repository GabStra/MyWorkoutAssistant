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
    
    val metadataParts = remember(
        exerciseLabel,
        supersetExerciseLabel,
        setLabel,
        sideIndicator,
        isUnilateral,
        equipmentName,
        accessoryNames
    ) {
        buildList {
            exerciseLabel?.let { add(it) }
            supersetExerciseLabel?.let { add(it) }
            setLabel?.let { add(it) }
            sideIndicator?.let { add(it) }
            if (isUnilateral) add("Unilateral")
            equipmentName?.let { add("Equipment: $it") }
            accessoryNames?.takeIf { it.isNotEmpty() }?.let { add("Accessory: $it") }
        }
    }
    
    val metadataText = remember(metadataParts) {
        metadataParts.joinToString(" | ")
    }
    
    val primaryColor = MaterialTheme.colorScheme.primary
    
    // Build annotated string for side indicator highlighting if needed
    val annotatedText = remember(metadataText, sideIndicator, currentSideIndex, primaryColor, textColor) {
        if (sideIndicator != null && currentSideIndex != null && sideIndicator.contains("↔") && metadataText.contains(sideIndicator)) {
            buildAnnotatedString {
                val parts = metadataText.split(" | ")
                parts.forEachIndexed { index, part ->
                    if (index > 0) {
                        append(" | ")
                    }
                    if (part == sideIndicator) {
                        // Highlight current side in side indicator
                        val sideParts = part.split(" ↔ ")
                        if (sideParts.size == 2) {
                            val (sideA, sideB) = sideParts
                            withStyle(
                                style = SpanStyle(
                                    color = if (currentSideIndex == 1u) {
                                        primaryColor
                                    } else {
                                        textColor
                                    },
                                    fontWeight = FontWeight.Bold
                                )
                            ) {
                                append(sideA)
                            }
                            append(" ↔ ")
                            withStyle(
                                style = SpanStyle(
                                    color = if (currentSideIndex == 2u) {
                                        primaryColor
                                    } else {
                                        textColor
                                    },
                                    fontWeight = FontWeight.Bold
                                )
                            ) {
                                append(sideB)
                            }
                        } else {
                            append(part)
                        }
                    } else {
                        append(part)
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
