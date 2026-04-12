package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.wear.compose.material3.MaterialTheme

/**
 * Metadata strip for superset pages. Shows only container-level info when relevant.
 */
@Composable
fun SupersetMetadataStrip(
    modifier: Modifier = Modifier,
    containerLabel: String? = null,
    onTap: (() -> Unit)? = null,
) {
    val baseStyle = MaterialTheme.typography.bodySmall
    val secondaryTextColor = MaterialTheme.colorScheme.onSurfaceVariant

    val metadataText = remember(
        containerLabel,
        baseStyle,
        secondaryTextColor
    ) {
        buildAnnotatedString {
            withStyle(baseStyle.toSpanStyle().copy(color = secondaryTextColor, fontWeight = FontWeight.Normal)) {
                fun pipe() {
                    withStyle(baseStyle.toSpanStyle().copy(fontWeight = FontWeight.Normal)) {
                        append(" | ")
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
        )
    }
}
