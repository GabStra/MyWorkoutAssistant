package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

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
    val clickableModifier = if (onTap != null) {
        modifier.clickable(onClick = onTap)
    } else {
        modifier
    }

    containerLabel?.let { label ->
        FlowRow(
            modifier = clickableModifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            Text(
                text = "Superset",
                style = baseStyle,
                color = secondaryTextColor,
                fontWeight = FontWeight.Normal
            )
            Text(
                text = label,
                style = baseStyle,
                color = secondaryTextColor,
                fontWeight = FontWeight.Normal
            )
        }
    }
}
