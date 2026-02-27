package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.MediumLighterGray

/**
 * Metadata strip for superset pages. Shows superset-specific info:
 * - Container label (e.g. "1/1") when multiple containers
 * - Exercise letters (A↔B)
 */
@Composable
fun SupersetMetadataStrip(
    modifier: Modifier = Modifier,
    containerLabel: String? = null,
    exerciseCount: Int,
    onTap: (() -> Unit)? = null,
) {
    val baseStyle = MaterialTheme.typography.bodySmall
    val primaryColor = MaterialTheme.colorScheme.primary
    val surfaceContainerHigh = MaterialTheme.colorScheme.surfaceContainerHigh
    val secondaryTextColor = MediumLighterGray

    val metadataText = remember(
        containerLabel,
        exerciseCount,
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
                    withStyle(baseStyle.toSpanStyle().copy(baselineShift = BaselineShift(0.25f))) {
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

                containerLabel?.let {
                    sep()
                    append("Superset ")
                    append(it)
                }

                if (exerciseCount > 0) {
                    sep()
                    (0 until exerciseCount).forEach { i ->
                        if (i > 0) {
                            separator()
                        }
                        withStyle(
                            SpanStyle(
                                color = primaryColor,
                                fontWeight = FontWeight.Bold
                            )
                        ) {
                            append(('A' + i).toString())
                        }
                    }
                }
            }
        }
    }

    if (metadataText.text.isNotEmpty()) {
        ScalableFadingText(
            text = metadataText,
            modifier = modifier.fillMaxWidth(),
            style = baseStyle,
            color = secondaryTextColor,
            onClick = onTap,
            minTextSize = baseStyle.fontSize,
            textAlign = TextAlign.Center
        )
    }
}
