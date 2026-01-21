package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.MediumLighterGray

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
    
    val baseStyle = MaterialTheme.typography.bodySmall
    val primaryColor = MaterialTheme.colorScheme.primary
    val surfaceContainerHigh = MaterialTheme.colorScheme.surfaceContainerHigh
    
    val metadataText = remember(
        exerciseLabel,
        supersetExerciseLabel,
        setLabel,
        sideIndicator,
        currentSideIndex,
        isUnilateral,
        equipmentName,
        accessoryNames,
        baseStyle,
        primaryColor,
        surfaceContainerHigh
    ) {
        buildAnnotatedString {
            fun pipe() {
                withStyle(
                    baseStyle.toSpanStyle().copy(
                        color = MediumLighterGray,
                        fontWeight = FontWeight.Thin
                    )
                ) {
                    append(" | ")
                }
            }
            
            fun separator() {
                withStyle(
                    baseStyle.toSpanStyle().copy(
                        color = MediumLighterGray,
                        baselineShift = BaselineShift(0.18f)
                    )
                ) {
                    append("↔")
                }
            }
            
            var first = true
            
            fun sep() {
                if (!first) {
                    pipe()
                }
                first = false
            }
            
            exerciseLabel?.let {
                sep()
                withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray)) {
                    append("Ex: ")
                }
                append(it)
            }
            
            if (supersetExerciseTotal != null && supersetExerciseIndex != null) {
                sep()
                pipe()
                (0 until supersetExerciseTotal).forEach { i ->
                    if (i > 0) {
                        separator()
                    }
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
            
            setLabel?.let {
                sep()
                withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray)) {
                    append("Set: ")
                }
                append(it)
            }
            
            sideIndicator?.let {
                sep()
                // For side indicator, use ① ↔ ② format
                val side1Color = if (currentSideIndex == 1u) primaryColor else surfaceContainerHigh
                val side2Color = if (currentSideIndex == 2u) primaryColor else surfaceContainerHigh
                
                withStyle(
                    SpanStyle(
                        color = side1Color,
                        fontWeight = FontWeight.Bold
                    )
                ) {
                    append("①")
                }
                separator()
                withStyle(
                    SpanStyle(
                        color = side2Color,
                        fontWeight = FontWeight.Bold
                    )
                ) {
                    append("②")
                }
            }
            
            if (isUnilateral) {
                sep()
                append("Unilateral")
            }
            
            equipmentName?.let {
                sep()
                withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray)) {
                    append("Eq: ")
                }
                append(it)
            }
            
            accessoryNames?.takeIf { it.isNotEmpty() }?.let {
                sep()
                withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray)) {
                    append("Acc: ")
                }
                append(it)
            }
        }
    }
    
    if (metadataText.text.isNotEmpty()) {
        FadingText(
            text = metadataText,
            modifier = modifier.fillMaxWidth(),
            style = baseStyle,
            color = textColor,
            marqueeEnabled = marqueeEnabled,
            onClick = {
                marqueeEnabled = !marqueeEnabled
                onTap?.invoke()
            }
        )
    }
}
