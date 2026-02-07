package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.wear.compose.material3.MaterialTheme

@Composable
fun ExerciseMetadataStrip(
    modifier: Modifier = Modifier,
    supersetExerciseIndex: Int? = null,
    supersetExerciseTotal: Int? = null,
    setLabel: String? = null,
    sideIndicator: String? = null,
    currentSideIndex: UInt? = null,
    isUnilateral: Boolean = false,
    textColor: Color = MaterialTheme.colorScheme.onBackground,
    onTap: (() -> Unit)? = null,
) {
    val baseStyle = MaterialTheme.typography.bodySmall
    val primaryColor = MaterialTheme.colorScheme.primary
    val surfaceContainerHigh = MaterialTheme.colorScheme.surfaceContainerHigh
    val secondaryTextColor = MediumLighterGray

    val metadataText = remember(
        supersetExerciseIndex,
        supersetExerciseTotal,
        setLabel,
        sideIndicator,
        currentSideIndex,
        isUnilateral,
        baseStyle,
        primaryColor,
        surfaceContainerHigh,
        secondaryTextColor
    ) {
        buildAnnotatedString {
            withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor, fontWeight = FontWeight.Normal)) {
                fun pipe() {
                    withStyle(baseStyle.toSpanStyle().copy(fontWeight = FontWeight.Normal)) {
                        append(" | ")
                    }
                }

                fun separator() {
                    withStyle(baseStyle.toSpanStyle().copy(baselineShift = BaselineShift(0.18f))) {
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

                if (supersetExerciseTotal != null && supersetExerciseIndex != null) {
                    sep()
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
                    append("Set: ")
                    append(it)
                }

                sideIndicator?.let {
                    sep()
                    val side1Color = if (currentSideIndex == 1u) primaryColor else surfaceContainerHigh
                    val side2Color = if (currentSideIndex == 2u) primaryColor else surfaceContainerHigh
                    withStyle(SpanStyle(color = side1Color, fontWeight = FontWeight.Bold)) {
                        append("①")
                    }
                    separator()
                    withStyle(SpanStyle(color = side2Color, fontWeight = FontWeight.Bold)) {
                        append("②")
                    }
                }

                if (isUnilateral) {
                    sep()
                    append("Unilateral")
                }
            }
        }
    }

    if (metadataText.text.isNotEmpty()) {
        FadingText(
            text = metadataText,
            modifier = modifier.fillMaxWidth(),
            style = baseStyle.copy(fontWeight = FontWeight.Normal),
            color = secondaryTextColor,
            onClick = {
                onTap?.invoke()
            },
            textAlign = TextAlign.Center
        )
    }
}
